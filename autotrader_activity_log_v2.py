from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from autotrader_strategy_catalog_v2 import (
    MACD_FLIP_STRATEGY_V2,
    MACD_LONG_FLAT_STRATEGY_V2,
    MACD_SHORT_FLAT_STRATEGY_V2,
)
from autotrader_strategy_enrollment_v2 import (
    ENTRY_MODE_APPROVAL_REQUIRED,
    ENTRY_MODE_AUTO,
    StrategyEnrollmentV2,
)
from database import connect

ENGINE_AUTOMANAGER = "AutoManager · MACD 30m"
ENGINE_GUARDIAN = "Position Guardian"
ENGINE_PILOT = "AutoManager"


@dataclass(frozen=True, slots=True)
class AutoManagerActivityEventV2:
    occurred_at: datetime
    engine: str
    title: str
    detail: str
    status: str
    realized_net_pnl: float | None = None
    currency: str | None = None


@dataclass(frozen=True, slots=True)
class AutoManagerActivityLogV2:
    pilot_key: str
    lifecycle_status: str
    next_step: str
    events: tuple[AutoManagerActivityEventV2, ...]


def _utc(value: Any) -> datetime:
    parsed = (
        value
        if isinstance(value, datetime)
        else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    )
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _record(row: Any, keys: tuple[str, ...]) -> dict[str, Any]:
    if isinstance(row, dict):
        return dict(row)
    return dict(zip(keys, row))


def _execution_status(status: str | None, block_reason: str | None) -> str:
    normalized = str(status or "").strip().upper()
    reason = str(block_reason or "").strip()
    labels = {
        "PENDING": "Venter på execution",
        "APPROVED": "Godkjent · venter på execution",
        "SUBMITTING": "Sendes til Saxo",
        "ORDER_ACCEPTED": "Ordre akseptert · venter på avstemming",
        "RECONCILED": "Ferdig avstemt",
        "SUPERSEDED": "Erstattet av nyere signal",
        "UNCERTAIN": "Uavklart · ingen blind retry",
    }
    if normalized == "BLOCKED":
        return f"Blokkert · {reason}" if reason else "Blokkert"
    if normalized == "REJECTED":
        return f"Avvist · {reason}" if reason else "Avvist"
    if normalized:
        return labels.get(normalized, normalized.replace("_", " ").title())
    return "Ingen ordre"


def _signal_title(
    signal: str, action: str | None, desired: str | None, observed: str
) -> tuple[str, str]:
    bullish = str(signal).upper() == "CROSS_UP"
    crossing = "Bullish kryss" if bullish else "Bearish kryss"
    normalized_action = str(action or "").upper()
    normalized_desired = str(desired or "").upper()
    if normalized_action == "CLOSE":
        return (
            f"{crossing} → CLOSE",
            f"Ba om exit fra {observed} til {normalized_desired or 'FLAT'}.",
        )
    if normalized_action == "OPEN":
        return (
            f"{crossing} → OPEN {normalized_desired}",
            f"Ba om ny {normalized_desired}-eksponering.",
        )
    return f"{crossing} → HOLD", f"Ingen ordre; posisjonen var allerede {observed}."


def _risk_title(reason: str) -> str:
    return {
        "HARD_STOP": "Hard stop → CLOSE",
        "TRAILING_STOP": "Trailing stop → CLOSE",
        "FIXED_TAKE_PROFIT": "Take profit → CLOSE",
    }.get(str(reason).upper(), f"{str(reason).replace('_', ' ').title()} → CLOSE")


def _next_signal(strategy_key: str, direction: str) -> tuple[str, str]:
    state = str(direction or "FLAT").upper()
    if strategy_key == MACD_LONG_FLAT_STRATEGY_V2:
        return ("bullish", "LONG") if state == "FLAT" else ("bearish", "FLAT")
    if strategy_key == MACD_SHORT_FLAT_STRATEGY_V2:
        return ("bearish", "SHORT") if state == "FLAT" else ("bullish", "FLAT")
    if strategy_key == MACD_FLIP_STRATEGY_V2:
        return (
            ("bullish", "LONG") if state in {"FLAT", "SHORT"} else ("bearish", "SHORT")
        )
    return ("nytt", "strategimål")


def build_automanager_lifecycle_status_v2(
    enrollment: StrategyEnrollmentV2,
    *,
    observed_direction: str,
    latest_strategy_close_signal: str | None = None,
    latest_strategy_close_at: datetime | None = None,
    latest_guardian_reason: str | None = None,
    latest_guardian_close_at: datetime | None = None,
    pending_action: str | None = None,
    pending_status: str | None = None,
    pending_block_reason: str | None = None,
    exact_close_authority: bool | None = None,
) -> tuple[str, str]:
    """Explain whether the pilot is exposed, temporarily flat, or actually stopped."""
    if not enrollment.enabled:
        return (
            "Pilot avsluttet",
            "Ingen nye strategiordrer opprettes før piloten aktiveres på nytt.",
        )

    request_status = str(pending_status or "").upper()
    if pending_action and request_status in {
        "PENDING",
        "APPROVED",
        "SUBMITTING",
        "ORDER_ACCEPTED",
        "UNCERTAIN",
    }:
        action = str(pending_action).upper()
        return (
            f"{action} under behandling",
            _execution_status(request_status, pending_block_reason),
        )

    direction = str(observed_direction or "FLAT").upper()
    signal, target = _next_signal(enrollment.strategy_key, direction)
    if direction != "FLAT":
        if exact_close_authority is False:
            return (
                f"{direction} · mangler eksakt CLOSE-authority",
                "Posisjonen observeres, men den nye Saxo-basen må eksplisitt overtas før AutoManager kan lukke den.",
            )
        return (
            f"{direction} · pilot aktiv",
            f"Overvåker neste lukkede 30m-bar; {signal} MACD-kryss gir mål {target}.",
        )

    guardian_is_latest = bool(
        latest_guardian_close_at
        and (
            latest_strategy_close_at is None
            or latest_guardian_close_at > latest_strategy_close_at
        )
    )
    if guardian_is_latest:
        reason = _risk_title(str(latest_guardian_reason or "RISK")).replace(
            " → CLOSE", ""
        )
        lifecycle = f"FLAT etter Position Guardian · {reason}"
    elif latest_strategy_close_signal:
        crossing = (
            "bearish" if latest_strategy_close_signal == "CROSS_DOWN" else "bullish"
        )
        lifecycle = f"FLAT pga. {crossing} 30m MACD-kryss"
    else:
        lifecycle = "FLAT · pilot aktiv"

    if enrollment.entry_mode == ENTRY_MODE_AUTO:
        authority = (
            "automatisk re-entry er armed"
            if enrollment.live_open_armed
            else "LIVE re-entry er ikke armed"
        )
        next_step = f"Venter på {signal} MACD-kryss mot {target}; {authority}."
    elif enrollment.entry_mode == ENTRY_MODE_APPROVAL_REQUIRED:
        next_step = (
            f"Venter på {signal} MACD-kryss mot {target}, deretter din godkjenning."
        )
    else:
        next_step = (
            "Venter på manuell entry; AutoManager kan fortsatt gjøre automatisk exit."
        )
    return lifecycle, next_step


def load_automanager_activity_log_v2(
    enrollment: StrategyEnrollmentV2,
    *,
    limit: int = 12,
) -> AutoManagerActivityLogV2:
    """Load durable strategy/risk provenance for one exact LIVE pilot."""
    with connect() as db:
        enrollment_row = db.execute(
            """
            SELECT enrolled_at, enabled
            FROM pg_v2_autotrader_strategy_enrollments
            WHERE pilot_key = ?
            """,
            (enrollment.pilot_key,),
        ).fetchone()
        latest_row = db.execute(
            """
            SELECT latest_closed_bar_time, observed_direction
            FROM pg_v2_autotrader_strategy_evaluations
            WHERE pilot_key = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (enrollment.pilot_key,),
        ).fetchone()
        strategy_rows = db.execute(
            """
            SELECT e.signal_at, e.signal, e.requested_action, e.desired_direction,
                   e.observed_direction, r.status, r.block_reason,
                   q.realized_net_pnl, q.currency
            FROM pg_v2_autotrader_strategy_evaluations e
            LEFT JOIN pg_v2_autotrader_execution_requests r
              ON r.request_id = e.execution_request_id
            LEFT JOIN pg_v2_autotrader_equity_reconciliations q
              ON q.close_event_id = r.request_id
            WHERE e.pilot_key = ? AND e.signal IS NOT NULL
            ORDER BY e.signal_at DESC, e.created_at DESC
            LIMIT ?
            """,
            (enrollment.pilot_key, max(1, int(limit))),
        ).fetchall()
        request_row = db.execute(
            """
            SELECT action, status, block_reason, updated_at
            FROM pg_v2_autotrader_execution_requests
            WHERE pilot_key = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (enrollment.pilot_key,),
        ).fetchone()
        basis_row = db.execute(
            """
            SELECT enrolled_at
            FROM pg_v2_autotrader_managed_positions
            WHERE account_id = ? AND uic = ? AND asset_type = ?
            ORDER BY enrolled_at DESC
            LIMIT 1
            """,
            (enrollment.account_id, int(enrollment.uic), enrollment.asset_type),
        ).fetchone()
        managed_basis_row = db.execute(
            """
            SELECT r.net_position_id, r.direction, r.amount, r.average_open_price,
                   m.managed, m.direction, m.amount, m.average_open_price
            FROM pg_v2_autotrader_risk_state r
            LEFT JOIN pg_v2_autotrader_managed_positions m
              ON m.account_id = r.account_id AND m.net_position_id = r.net_position_id
            WHERE r.account_id = ? AND r.uic = ? AND r.asset_type = ?
              AND r.active = TRUE
            ORDER BY r.last_seen_at DESC
            LIMIT 1
            """,
            (enrollment.account_id, int(enrollment.uic), enrollment.asset_type),
        ).fetchone()

        enrolled_at = None
        if enrollment_row is not None:
            enrolled = _record(enrollment_row, ("enrolled_at", "enabled"))
            enrolled_at = _utc(enrolled["enrolled_at"])
        if enrolled_at is None:
            enrolled_at = datetime.now(timezone.utc)

        risk_rows = db.execute(
            """
            SELECT e.created_at, e.reason, e.pnl_pct, a.status, a.error_message,
                   q.realized_net_pnl, q.currency
            FROM pg_v2_autotrader_risk_events e
            LEFT JOIN pg_v2_autotrader_live_close_attempts a
              ON a.event_id = e.event_id
            LEFT JOIN pg_v2_autotrader_equity_reconciliations q
              ON q.close_event_id = e.event_id
            WHERE e.account_id = ? AND e.uic = ? AND e.asset_type = ?
              AND e.created_at >= ?
            ORDER BY e.created_at DESC
            LIMIT ?
            """,
            (
                enrollment.account_id,
                int(enrollment.uic),
                enrollment.asset_type,
                enrolled_at,
                max(1, int(limit)),
            ),
        ).fetchall()

    events: list[AutoManagerActivityEventV2] = []
    basis_started_at = enrolled_at
    if basis_row is not None:
        basis = _record(basis_row, ("enrolled_at",))
        basis_started_at = _utc(basis["enrolled_at"])
    latest_strategy_close_signal = None
    latest_strategy_close_at = None
    strategy_keys = (
        "signal_at",
        "signal",
        "requested_action",
        "desired_direction",
        "observed_direction",
        "status",
        "block_reason",
        "realized_net_pnl",
        "currency",
    )
    for row in strategy_rows:
        item = _record(row, strategy_keys)
        signal_at = _utc(item["signal_at"])
        title, detail = _signal_title(
            str(item["signal"]),
            item.get("requested_action"),
            item.get("desired_direction"),
            str(item.get("observed_direction") or "FLAT"),
        )
        events.append(
            AutoManagerActivityEventV2(
                occurred_at=signal_at,
                engine=ENGINE_AUTOMANAGER,
                title=title,
                detail=detail,
                status=_execution_status(item.get("status"), item.get("block_reason")),
                realized_net_pnl=None
                if item.get("realized_net_pnl") is None
                else float(item["realized_net_pnl"]),
                currency=None
                if item.get("currency") is None
                else str(item["currency"]),
            )
        )
        if (
            signal_at >= basis_started_at
            and str(item.get("requested_action") or "").upper() == "CLOSE"
            and str(item.get("status") or "").upper() == "RECONCILED"
            and str(item.get("block_reason") or "").upper() != "ALREADY_FLAT_NO_ORDER"
            and (
                latest_strategy_close_at is None or signal_at > latest_strategy_close_at
            )
        ):
            latest_strategy_close_at = signal_at
            latest_strategy_close_signal = str(item["signal"])

    latest_guardian_reason = None
    latest_guardian_close_at = None
    risk_keys = (
        "created_at",
        "reason",
        "pnl_pct",
        "status",
        "error_message",
        "realized_net_pnl",
        "currency",
    )
    for row in risk_rows:
        item = _record(row, risk_keys)
        occurred_at = _utc(item["created_at"])
        if (
            occurred_at >= basis_started_at
            and str(item.get("status") or "").upper() == "RECONCILED"
            and (
                latest_guardian_close_at is None
                or occurred_at > latest_guardian_close_at
            )
        ):
            latest_guardian_close_at = occurred_at
            latest_guardian_reason = str(item["reason"])
        events.append(
            AutoManagerActivityEventV2(
                occurred_at=occurred_at,
                engine=ENGINE_GUARDIAN,
                title=_risk_title(str(item["reason"])),
                detail=f"Posisjonsavkastning ved trigger: {float(item['pnl_pct']):+.2f}%.",
                status=_execution_status(item.get("status"), item.get("error_message")),
                realized_net_pnl=None
                if item.get("realized_net_pnl") is None
                else float(item["realized_net_pnl"]),
                currency=None
                if item.get("currency") is None
                else str(item["currency"]),
            )
        )

    events.append(
        AutoManagerActivityEventV2(
            occurred_at=enrolled_at,
            engine=ENGINE_PILOT,
            title="Pilot aktivert",
            detail=f"{enrollment.strategy_key} · {enrollment.execution_mode}",
            status="Aktiv" if enrollment.enabled else "Avsluttet",
        )
    )
    events.sort(key=lambda item: item.occurred_at, reverse=True)

    observed_direction = "FLAT"
    if latest_row is not None:
        latest = _record(latest_row, ("latest_closed_bar_time", "observed_direction"))
        observed_direction = str(latest.get("observed_direction") or "FLAT")
    exact_close_authority = None
    if managed_basis_row is not None:
        basis = _record(
            managed_basis_row,
            (
                "net_position_id",
                "observed_direction",
                "observed_amount",
                "observed_average_open_price",
                "managed",
                "managed_direction",
                "managed_amount",
                "managed_average_open_price",
            ),
        )
        exact_close_authority = bool(
            basis.get("managed")
            and str(basis.get("observed_direction") or "").lower()
            == str(basis.get("managed_direction") or "").lower()
            and abs(
                float(basis.get("observed_amount") or 0.0)
                - float(basis.get("managed_amount") or 0.0)
            )
            <= 1e-12
            and abs(
                float(basis.get("observed_average_open_price") or 0.0)
                - float(basis.get("managed_average_open_price") or 0.0)
            )
            <= 1e-12
        )
    pending_action = pending_status = pending_reason = None
    if request_row is not None:
        request = _record(
            request_row, ("action", "status", "block_reason", "updated_at")
        )
        pending_action = (
            None if request.get("action") is None else str(request["action"])
        )
        pending_status = (
            None if request.get("status") is None else str(request["status"])
        )
        pending_reason = (
            None
            if request.get("block_reason") is None
            else str(request["block_reason"])
        )

    lifecycle, next_step = build_automanager_lifecycle_status_v2(
        enrollment,
        observed_direction=observed_direction,
        latest_strategy_close_signal=latest_strategy_close_signal,
        latest_strategy_close_at=latest_strategy_close_at,
        latest_guardian_reason=latest_guardian_reason,
        latest_guardian_close_at=latest_guardian_close_at,
        pending_action=pending_action,
        pending_status=pending_status,
        pending_block_reason=pending_reason,
        exact_close_authority=exact_close_authority,
    )
    return AutoManagerActivityLogV2(
        pilot_key=enrollment.pilot_key,
        lifecycle_status=lifecycle,
        next_step=next_step,
        events=tuple(events[: max(1, int(limit))]),
    )


__all__ = [
    "ENGINE_AUTOMANAGER",
    "ENGINE_GUARDIAN",
    "ENGINE_PILOT",
    "AutoManagerActivityEventV2",
    "AutoManagerActivityLogV2",
    "build_automanager_lifecycle_status_v2",
    "load_automanager_activity_log_v2",
]
