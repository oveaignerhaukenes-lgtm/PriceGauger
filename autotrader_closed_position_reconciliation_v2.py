from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import math
import time
from typing import Any

from autotrader_pilot_equity_v2 import load_pilot_equity_v2, record_realized_net_pnl_v2
from autotrader_schema_v2 import ensure_autotrader_schema_v2
from autotrader_strategy_enrollment_v2 import find_strategy_enrollment_for_close_v2
from database import connect
from saxo_provider import configured_client


LOGGER = logging.getLogger("pricegauger.autotrader.closed_position_reconciliation_v2")
ELIGIBLE_ATTEMPT_STATUSES = ("ORDER_ACCEPTED", "RECONCILED")
SOURCE_KIND = "SAXO_CLOSED_POSITION"
RISK_REENTRY_BLOCK_REASON = "RISK_CLOSE_REQUIRES_FRESH_SIGNAL"


@dataclass(frozen=True, slots=True)
class ClosedPositionRealizationV2:
    unique_id: str
    account_id: str
    uic: int
    asset_type: str
    amount: float
    closing_external_reference: str
    closing_position_id: str
    closed_profit_loss_base: float
    opening_cost_base: float
    closing_cost_base: float
    execution_time_close: str | None

    @property
    def realized_net_pnl(self) -> float:
        # Saxo documentation exposes closed P/L and costs separately. Cost sign has
        # varied across examples/API generations, so abs() deliberately treats any
        # non-zero cost as a deduction. This is conservative for capital sizing.
        return (
            float(self.closed_profit_loss_base)
            - abs(float(self.opening_cost_base))
            - abs(float(self.closing_cost_base))
        )


def _finite(value: Any, *, field: str, default: float | None = None) -> float:
    if value is None and default is not None:
        return float(default)
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"closed position {field} is not numeric") from exc
    if not math.isfinite(number):
        raise ValueError(f"closed position {field} must be finite")
    return number


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def closed_position_realizations_v2(payload: dict[str, Any]) -> tuple[ClosedPositionRealizationV2, ...]:
    rows = payload.get("Data") or []
    if not isinstance(rows, list):
        raise ValueError("Saxo closed positions Data must be a list")
    items: list[ClosedPositionRealizationV2] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        closed = row.get("ClosedPosition")
        if not isinstance(closed, dict):
            continue
        reference = str(closed.get("ClosingExternalReferenceId") or "").strip()
        account_id = str(closed.get("AccountId") or "").strip()
        asset_type = str(closed.get("AssetType") or "").strip()
        unique_id = str(row.get("ClosedPositionUniqueId") or "").strip()
        closing_position_id = str(closed.get("ClosingPositionId") or "").strip()
        uic = int(closed.get("Uic") or 0)
        amount = _finite(closed.get("Amount"), field="Amount")
        if not reference or not account_id or not asset_type or not unique_id or not closing_position_id:
            continue
        if uic <= 0 or amount <= 0:
            continue
        items.append(
            ClosedPositionRealizationV2(
                unique_id=unique_id,
                account_id=account_id,
                uic=uic,
                asset_type=asset_type,
                amount=amount,
                closing_external_reference=reference,
                closing_position_id=closing_position_id,
                closed_profit_loss_base=_finite(
                    closed.get("ClosedProfitLossInBaseCurrency"),
                    field="ClosedProfitLossInBaseCurrency",
                ),
                opening_cost_base=_finite(
                    closed.get("CostOpeningInBaseCurrency"),
                    field="CostOpeningInBaseCurrency",
                    default=0.0,
                ),
                closing_cost_base=_finite(
                    closed.get("CostClosingInBaseCurrency"),
                    field="CostClosingInBaseCurrency",
                    default=0.0,
                ),
                execution_time_close=(
                    str(closed.get("ExecutionTimeClose"))
                    if closed.get("ExecutionTimeClose") is not None
                    else None
                ),
            )
        )
    return tuple(items)


def match_close_realizations_v2(
    *,
    realizations: tuple[ClosedPositionRealizationV2, ...],
    account_id: str,
    uic: int,
    asset_type: str,
    external_reference: str,
    expected_amount: float,
) -> tuple[ClosedPositionRealizationV2, ...]:
    matches = tuple(
        item
        for item in realizations
        if item.account_id == str(account_id)
        and item.uic == int(uic)
        and item.asset_type == str(asset_type)
        and item.closing_external_reference == str(external_reference)
    )
    if not matches:
        return ()
    matched_amount = sum(item.amount for item in matches)
    tolerance = max(1e-9, abs(float(expected_amount)) * 1e-9)
    if matched_amount + tolerance < float(expected_amount):
        # A closing order can fan out across several opening positions. Never book
        # a partial snapshot and then double-count when the remaining rows arrive.
        return ()
    return matches


def realized_net_pnl_v2(items: tuple[ClosedPositionRealizationV2, ...]) -> float:
    if not items:
        raise ValueError("at least one closed position realization is required")
    value = sum(item.realized_net_pnl for item in items)
    if not math.isfinite(value):
        raise ValueError("realized net P/L must be finite")
    return value


def risk_flat_since_v2(items: tuple[ClosedPositionRealizationV2, ...]) -> datetime | None:
    """Return authoritative latest Saxo close execution time, or None fail-closed.

    A split close is considered flat only after its latest closing execution. If any
    matched row lacks a trustworthy close time, callers conservatively invalidate
    every still-unstarted re-entry rather than guessing a freshness boundary.
    """
    if not items:
        return None
    times: list[datetime] = []
    for item in items:
        if not item.execution_time_close:
            return None
        try:
            times.append(_utc(item.execution_time_close))
        except (TypeError, ValueError):
            return None
    return max(times) if times else None


def _account_contexts_v2(client) -> dict[str, dict[str, str]]:
    payload = client._get("port/v1/accounts/me")
    rows = payload.get("Data") or []
    if not isinstance(rows, list):
        raise RuntimeError("Saxo accounts response had invalid Data format")
    result: dict[str, dict[str, str]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        account_id = str(row.get("AccountId") or "").strip()
        account_key = str(row.get("AccountKey") or "").strip()
        client_key = str(row.get("ClientKey") or "").strip()
        currency = str(row.get("Currency") or "").strip().upper()
        if account_id and account_key and client_key and currency:
            result[account_id] = {
                "account_key": account_key,
                "client_key": client_key,
                "currency": currency,
            }
    return result


def _candidate_attempts_v2() -> tuple[dict[str, Any], ...]:
    with connect() as db:
        rows = db.execute(
            """
            SELECT attempts.event_id, attempts.account_id, attempts.net_position_id,
                   attempts.uic, attempts.asset_type, attempts.amount,
                   attempts.external_reference, attempts.status
            FROM pg_v2_autotrader_live_close_attempts AS attempts
            LEFT JOIN pg_v2_autotrader_equity_reconciliations AS booked
              ON booked.close_event_id = attempts.event_id
            WHERE attempts.status IN (?, ?)
              AND booked.close_event_id IS NULL
            ORDER BY attempts.updated_at ASC
            """,
            ELIGIBLE_ATTEMPT_STATUSES,
        ).fetchall()
    return tuple(dict(row) for row in rows)


def invalidate_stale_reentry_after_risk_close_v2(
    *,
    close_event_id: str,
    pilot_key: str,
    flat_since: datetime | None,
) -> bool:
    """Invalidate only stale, unstarted entry authority after a PG risk-origin close.

    Strategy-origin reversal CLOSE requests use execution-request IDs and therefore
    do not exist in `pg_v2_autotrader_risk_events`; they keep their normal pending
    CLOSE -> FLAT -> OPEN intent. Risk-origin exits instead establish a freshness
    boundary: only a MACD cross strictly after Saxo's confirmed flat time may open.
    """
    with connect() as db:
        risk_event = db.execute(
            "SELECT reason FROM pg_v2_autotrader_risk_events WHERE event_id = ?",
            (str(close_event_id),),
        ).fetchone()
        if risk_event is None:
            return False

        if flat_since is None:
            db.execute(
                """
                UPDATE pg_v2_autotrader_execution_requests
                SET status = 'SUPERSEDED', block_reason = ?, updated_at = now()
                WHERE pilot_key = ? AND action = 'OPEN'
                  AND status IN ('PENDING', 'APPROVED')
                """,
                (RISK_REENTRY_BLOCK_REASON, str(pilot_key)),
            )
            db.execute(
                """
                UPDATE pg_v2_autotrader_strategy_runtime_state
                SET pending_intent_id = NULL, pending_signal_at = NULL,
                    pending_signal = NULL, pending_target_direction = NULL,
                    pending_previous_macd = NULL, pending_previous_signal = NULL,
                    pending_current_macd = NULL, pending_current_signal = NULL,
                    pending_budget_amount = NULL, pending_budget_currency = NULL,
                    updated_at = now()
                WHERE pilot_key = ? AND pending_intent_id IS NOT NULL
                """,
                (str(pilot_key),),
            )
        else:
            boundary = flat_since.astimezone(timezone.utc)
            db.execute(
                """
                UPDATE pg_v2_autotrader_execution_requests
                SET status = 'SUPERSEDED', block_reason = ?, updated_at = now()
                WHERE pilot_key = ? AND action = 'OPEN'
                  AND status IN ('PENDING', 'APPROVED')
                  AND signal_at <= ?
                """,
                (RISK_REENTRY_BLOCK_REASON, str(pilot_key), boundary),
            )
            db.execute(
                """
                UPDATE pg_v2_autotrader_strategy_runtime_state
                SET pending_intent_id = NULL, pending_signal_at = NULL,
                    pending_signal = NULL, pending_target_direction = NULL,
                    pending_previous_macd = NULL, pending_previous_signal = NULL,
                    pending_current_macd = NULL, pending_current_signal = NULL,
                    pending_budget_amount = NULL, pending_budget_currency = NULL,
                    updated_at = now()
                WHERE pilot_key = ? AND pending_intent_id IS NOT NULL
                  AND (pending_signal_at IS NULL OR pending_signal_at <= ?)
                """,
                (str(pilot_key), boundary),
            )
    return True


def _record_reconciliation_v2(
    *,
    close_event_id: str,
    pilot_key: str,
    external_reference: str,
    closed_items: tuple[ClosedPositionRealizationV2, ...],
    realized_net_pnl: float,
    currency: str,
) -> None:
    unique_ids = ",".join(sorted(item.unique_id for item in closed_items))
    closing_ids = ",".join(sorted(item.closing_position_id for item in closed_items))
    gross = sum(item.closed_profit_loss_base for item in closed_items)
    open_cost = sum(abs(item.opening_cost_base) for item in closed_items)
    close_cost = sum(abs(item.closing_cost_base) for item in closed_items)
    with connect() as db:
        db.execute(
            """
            INSERT INTO pg_v2_autotrader_equity_reconciliations(
                close_event_id, pilot_key, closing_external_reference,
                closed_position_unique_ids, closing_position_ids,
                gross_pnl_base, opening_cost_base, closing_cost_base,
                realized_net_pnl, currency, reconciled_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, now())
            ON CONFLICT (close_event_id) DO NOTHING
            """,
            (
                str(close_event_id),
                str(pilot_key),
                str(external_reference),
                unique_ids,
                closing_ids,
                gross,
                open_cost,
                close_cost,
                float(realized_net_pnl),
                str(currency).upper(),
            ),
        )


def reconcile_closed_position_equity_once_v2(client=None) -> int:
    """Book exact realized net P/L after a guarded LIVE close has settled.

    A close only affects strategy equity when it can be joined to an active strategy
    enrollment and authoritative Saxo closed-position rows carrying the exact
    `ClosingExternalReferenceId` generated by PriceGauger. Closed positions are
    requested at account scope so base-currency P/L is the account currency.
    """
    ensure_autotrader_schema_v2()
    attempts = _candidate_attempts_v2()
    if not attempts:
        return 0
    client = client or configured_client()
    if client is None:
        raise RuntimeError("Saxo client is not configured")
    account_contexts = _account_contexts_v2(client)
    closed_by_account: dict[str, tuple[ClosedPositionRealizationV2, ...]] = {}
    booked = 0

    for attempt in attempts:
        enrollment = find_strategy_enrollment_for_close_v2(
            account_id=str(attempt["account_id"]),
            net_position_id=str(attempt["net_position_id"]),
            uic=int(attempt["uic"]),
            asset_type=str(attempt["asset_type"]),
        )
        if enrollment is None:
            continue
        account_id = str(attempt["account_id"])
        account = account_contexts.get(account_id)
        if account is None:
            LOGGER.warning("P/L reconciliation blocked: exact Saxo account context unavailable account=%s", account_id)
            continue
        if account_id not in closed_by_account:
            payload = client._get(
                "port/v1/closedpositions",
                params={
                    "AccountKey": account["account_key"],
                    "ClientKey": account["client_key"],
                    "$top": 1000,
                    "FieldGroups": "ClosedPosition",
                },
            )
            closed_by_account[account_id] = closed_position_realizations_v2(payload)
        matches = match_close_realizations_v2(
            realizations=closed_by_account[account_id],
            account_id=account_id,
            uic=int(attempt["uic"]),
            asset_type=str(attempt["asset_type"]),
            external_reference=str(attempt["external_reference"]),
            expected_amount=float(attempt["amount"]),
        )
        if not matches:
            continue
        account_currency = account["currency"]
        equity = load_pilot_equity_v2(pilot_key=enrollment.pilot_key)
        if equity.currency.upper() != account_currency.upper():
            LOGGER.error(
                "P/L reconciliation blocked: pilot currency=%s account currency=%s pilot=%s",
                equity.currency,
                account_currency,
                enrollment.pilot_key,
            )
            continue
        net_pnl = realized_net_pnl_v2(matches)
        source_reference = f"close-attempt:{attempt['event_id']}"
        record_realized_net_pnl_v2(
            pilot_key=enrollment.pilot_key,
            source_reference=source_reference,
            realized_net_pnl=net_pnl,
            currency=account_currency,
            source_kind=SOURCE_KIND,
        )

        # OPEN already blocks while this close lacks an equity reconciliation row.
        # Invalidate stale risk-stop intent before inserting that row, so there is
        # no interval where a reconciled risk close can release an old OPEN request.
        risk_invalidated = invalidate_stale_reentry_after_risk_close_v2(
            close_event_id=str(attempt["event_id"]),
            pilot_key=enrollment.pilot_key,
            flat_since=risk_flat_since_v2(matches),
        )
        _record_reconciliation_v2(
            close_event_id=str(attempt["event_id"]),
            pilot_key=enrollment.pilot_key,
            external_reference=str(attempt["external_reference"]),
            closed_items=matches,
            realized_net_pnl=net_pnl,
            currency=account_currency,
        )
        booked += 1
        LOGGER.info(
            "AutoTrader realized P/L booked pilot=%s event=%s net_pnl=%+.4f %s rows=%d risk_reentry_invalidated=%s",
            enrollment.pilot_key,
            attempt["event_id"],
            net_pnl,
            account_currency,
            len(matches),
            risk_invalidated,
        )
    return booked


def run_closed_position_equity_reconciliation_forever_v2(*, interval_seconds: int = 5) -> None:
    interval = max(2, int(interval_seconds))
    while True:
        try:
            reconcile_closed_position_equity_once_v2()
        except Exception as exc:
            LOGGER.warning("closed-position equity reconciliation failed: %s", exc, exc_info=True)
        time.sleep(interval)


__all__ = [
    "ClosedPositionRealizationV2",
    "RISK_REENTRY_BLOCK_REASON",
    "closed_position_realizations_v2",
    "invalidate_stale_reentry_after_risk_close_v2",
    "match_close_realizations_v2",
    "realized_net_pnl_v2",
    "reconcile_closed_position_equity_once_v2",
    "risk_flat_since_v2",
    "run_closed_position_equity_reconciliation_forever_v2",
]
