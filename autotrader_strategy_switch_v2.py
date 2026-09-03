from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from autotrader_entry_policy_v2 import load_pilot_margin_config_v2
from autotrader_mtf_live_runtime_v2 import ensure_mtf_live_schema_v2
from autotrader_mtf_short_live_runtime_v2 import ensure_mtf_short_live_schema_v2
from autotrader_pilot_equity_v2 import load_pilot_equity_v2
from autotrader_risk_control_v2 import PositionObservationV2, _position_observations_v2
from autotrader_schema_v2 import ensure_autotrader_schema_v2
from autotrader_strategy_catalog_v2 import strategy_spec_v2
from autotrader_strategy_enrollment_v2 import (
    EXECUTION_MODE_LIVE,
    StrategyEnrollmentV2,
    load_strategy_enrollment_v2,
)
from autotrader_strategy_switch_provenance_v2 import ensure_strategy_switch_provenance_schema_v2
from database import connect
from saxo_provider import LIVE_BASE_URL, configured_client


INFLIGHT_EXECUTION_STATUSES = ("SUBMITTING", "ORDER_ACCEPTED", "UNCERTAIN")


@dataclass(frozen=True, slots=True)
class StrategySwitchResultV2:
    from_pilot_key: str
    to_pilot_key: str
    from_strategy_key: str
    to_strategy_key: str
    observed_direction: str
    entry_mode: str
    live_open_was_armed: bool


def ensure_hot_strategy_switch_schema_v2() -> None:
    """Persist the exact market/exposure mark at a strategy handoff.

    The mark is deliberately separate from settled Saxo P/L. Switching strategy does
    not synthesize a close, mutate the real position or book unrealized profit/loss.
    It only creates the audit boundary needed to attribute strategy performance later.
    """
    ensure_strategy_switch_provenance_schema_v2()
    with connect() as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS pg_v2_autotrader_strategy_switch_marks (
                event_id UUID PRIMARY KEY REFERENCES pg_v2_autotrader_strategy_switch_events(event_id),
                account_id TEXT NOT NULL,
                uic BIGINT NOT NULL,
                asset_type TEXT NOT NULL,
                observed_direction TEXT NOT NULL,
                observed_net_position_id TEXT,
                observed_amount DOUBLE PRECISION,
                observed_average_open_price DOUBLE PRECISION,
                observed_mark_price DOUBLE PRECISION,
                observed_pnl_pct DOUBLE PRECISION,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )


def _direction_v2(observation: PositionObservationV2 | None) -> str:
    if observation is None:
        return "FLAT"
    side = observation.direction.strip().lower()
    if side == "buy":
        return "LONG"
    if side == "sell":
        return "SHORT"
    raise ValueError(f"unsupported Saxo position direction during strategy switch: {observation.direction}")


def _observed_product_state_v2(enrollment: StrategyEnrollmentV2) -> PositionObservationV2 | None:
    """Read exact LIVE exposure without requiring FLAT.

    A hot strategy handoff may adopt LONG, SHORT or FLAT. We still reject a working
    Saxo order on the same product because a position mutation already in flight makes
    the handoff basis ambiguous; that is transaction safety, not a trading-policy gate.
    """
    client = configured_client()
    if client is None or client.base_url.rstrip("/").lower() != LIVE_BASE_URL.lower():
        raise RuntimeError("Saxo LIVE is required to switch an active LIVE strategy")

    observations = tuple(
        item
        for item in _position_observations_v2(client)
        if item.account_id == enrollment.account_id
        and int(item.uic) == int(enrollment.uic)
        and item.asset_type == enrollment.asset_type
    )
    if len(observations) > 1:
        raise RuntimeError("multiple Saxo positions match the active AutoManager product")
    observation = observations[0] if observations else None

    accounts = client._get("port/v1/accounts/me")
    rows = accounts.get("Data") or []
    account_key = None
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict) and str(row.get("AccountId") or "") == enrollment.account_id:
                account_key = str(row.get("AccountKey") or "").strip()
                break
    if not account_key:
        raise RuntimeError("could not resolve Saxo AccountKey while switching strategy")

    orders = client._get("port/v1/orders/me", params={"$top": 1000})
    order_rows = orders.get("Data") or []
    if not isinstance(order_rows, list):
        raise RuntimeError("Saxo open-order list had invalid format during strategy switch")
    if any(
        isinstance(row, dict)
        and str(row.get("AccountKey") or "") == account_key
        and int(row.get("Uic") or -1) == int(enrollment.uic)
        for row in order_rows
    ):
        raise ValueError("strategy switch waits while a Saxo order is working on this product")
    return observation


def _pg_execution_inflight_v2(enrollment: StrategyEnrollmentV2) -> bool:
    with connect() as db:
        request = db.execute(
            """
            SELECT request_id
            FROM pg_v2_autotrader_execution_requests
            WHERE account_id = ? AND uic = ? AND asset_type = ?
              AND status IN (?, ?, ?)
            LIMIT 1
            """,
            (
                enrollment.account_id,
                int(enrollment.uic),
                enrollment.asset_type,
                *INFLIGHT_EXECUTION_STATUSES,
            ),
        ).fetchone()
        if request is not None:
            return True
        open_attempt = db.execute(
            """
            SELECT request_id
            FROM pg_v2_autotrader_live_open_attempts
            WHERE account_id = ? AND uic = ? AND asset_type = ?
              AND status IN (?, ?, ?)
            LIMIT 1
            """,
            (
                enrollment.account_id,
                int(enrollment.uic),
                enrollment.asset_type,
                *INFLIGHT_EXECUTION_STATUSES,
            ),
        ).fetchone()
        if open_attempt is not None:
            return True
        close_attempt = db.execute(
            """
            SELECT event_id
            FROM pg_v2_autotrader_live_close_attempts
            WHERE account_id = ? AND uic = ? AND asset_type = ?
              AND status IN (?, ?, ?)
            LIMIT 1
            """,
            (
                enrollment.account_id,
                int(enrollment.uic),
                enrollment.asset_type,
                *INFLIGHT_EXECUTION_STATUSES,
            ),
        ).fetchone()
    return close_attempt is not None


def _quiesce_source_authority_v2(enrollment: StrategyEnrollmentV2) -> None:
    """Supersede only unstarted strategy intents before the ownership handoff."""
    with connect() as db:
        db.execute(
            """
            UPDATE pg_v2_autotrader_execution_requests
            SET status = 'SUPERSEDED', block_reason = 'STRATEGY_SWITCH', updated_at = now()
            WHERE pilot_key = ? AND status IN ('PENDING', 'APPROVED')
            """,
            (enrollment.pilot_key,),
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
            WHERE pilot_key = ?
            """,
            (enrollment.pilot_key,),
        )


def _target_equity_state_exists_v2(target_pilot_key: str) -> bool:
    with connect() as db:
        row = db.execute(
            "SELECT 1 FROM pg_v2_autotrader_pilot_equity_state WHERE pilot_key = ? LIMIT 1",
            (str(target_pilot_key),),
        ).fetchone()
    return row is not None


def switch_live_strategy_v2(
    *,
    pilot_key: str,
    target_strategy_key: str,
) -> StrategySwitchResultV2:
    """Hot-switch one exact LIVE product to another strategy without trading it.

    LONG/SHORT/FLAT exposure is observed once and carried unchanged into the target
    strategy cohort. The switch itself never POSTs an order and never fabricates a
    close merely to make accounting convenient. Old unstarted intents are superseded,
    target runtime state is empty (no signal replay), and the current OPEN arming +
    entry-mode policy is preserved.

    Settled pilot capital remains authoritative for sizing. If an open position is
    handed over, its eventual authoritative Saxo close is booked normally; the exact
    switch mark is persisted separately so strategy-performance attribution can split
    the move at the handoff without contaminating the settled capital ledger.
    """
    ensure_autotrader_schema_v2()
    ensure_mtf_live_schema_v2()
    ensure_mtf_short_live_schema_v2()
    ensure_hot_strategy_switch_schema_v2()

    enrollment = load_strategy_enrollment_v2(str(pilot_key))
    if enrollment is None or not enrollment.enabled:
        raise LookupError("active AutoManager pilot not found")
    if enrollment.execution_mode != EXECUTION_MODE_LIVE:
        raise ValueError("only a LIVE AutoManager pilot can switch LIVE strategy")

    target = strategy_spec_v2(str(target_strategy_key))
    if target.key == enrollment.strategy_key:
        return StrategySwitchResultV2(
            from_pilot_key=enrollment.pilot_key,
            to_pilot_key=enrollment.pilot_key,
            from_strategy_key=enrollment.strategy_key,
            to_strategy_key=target.key,
            observed_direction="UNCHANGED",
            entry_mode=enrollment.entry_mode,
            live_open_was_armed=enrollment.live_open_armed,
        )

    if _pg_execution_inflight_v2(enrollment):
        raise ValueError("strategy switch waits while PriceGauger execution is already in flight")

    # Remove old unstarted signal authority before taking the external exposure mark.
    # If the external read fails, the source remains enabled and can continue from a
    # fresh signal; no live_open_armed policy is silently changed.
    _quiesce_source_authority_v2(enrollment)
    observed = _observed_product_state_v2(enrollment)
    observed_direction = _direction_v2(observed)

    target_pilot_key = enrollment.product.pilot_key(target.key)
    target_existing = load_strategy_enrollment_v2(target_pilot_key)
    if target_existing is not None or _target_equity_state_exists_v2(target_pilot_key):
        raise ValueError(
            "target strategy pilot already has history; resuming a prior strategy cohort is not enabled yet"
        )

    source_equity = load_pilot_equity_v2(pilot_key=enrollment.pilot_key)
    source_margin = load_pilot_margin_config_v2(enrollment.pilot_key)
    event_id = str(uuid4())
    anchor = "" if observed is None else observed.net_position_id
    flat_handoff = observed is None
    provenance_kind = "CONFIRMED_FLAT_STRATEGY_HANDOFF" if flat_handoff else "OPEN_POSITION_STRATEGY_HANDOFF"

    with connect() as db:
        # Repeat the supersede in the control-plane transaction in case a fresh
        # unstarted request appeared between quiesce and the Saxo observation.
        db.execute(
            """
            UPDATE pg_v2_autotrader_execution_requests
            SET status = 'SUPERSEDED', block_reason = 'STRATEGY_SWITCH', updated_at = now()
            WHERE pilot_key = ? AND status IN ('PENDING', 'APPROVED')
            """,
            (enrollment.pilot_key,),
        )
        db.execute(
            """
            INSERT INTO pg_v2_autotrader_pilot_equity_state(
                pilot_key, seed_capital, currency, created_at, updated_at
            ) VALUES (?, ?, ?, now(), now())
            """,
            (target_pilot_key, float(source_equity.equity), source_equity.currency),
        )
        db.execute(
            """
            UPDATE pg_v2_autotrader_strategy_enrollments
            SET enabled = FALSE, live_open_armed = FALSE, updated_at = now()
            WHERE pilot_key = ? AND enabled = TRUE AND execution_mode = ?
            """,
            (enrollment.pilot_key, EXECUTION_MODE_LIVE),
        )
        db.execute(
            """
            INSERT INTO pg_v2_autotrader_strategy_enrollments(
                pilot_key, strategy_key, execution_mode, account_id, anchor_net_position_id,
                uic, asset_type, market_id, instrument_id, market_name,
                enabled, live_open_armed, entry_mode, enrolled_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, TRUE, ?, ?, now(), now())
            """,
            (
                target_pilot_key,
                target.key,
                EXECUTION_MODE_LIVE,
                enrollment.account_id,
                anchor,
                int(enrollment.uic),
                enrollment.asset_type,
                int(enrollment.market_id),
                int(enrollment.instrument_id),
                enrollment.market_name,
                bool(enrollment.live_open_armed),
                enrollment.entry_mode,
            ),
        )
        if source_margin is not None:
            db.execute(
                """
                INSERT INTO pg_v2_autotrader_margin_configs(
                    pilot_key, enabled, max_effective_leverage,
                    minimum_free_capital, updated_at
                ) VALUES (?, ?, ?, ?, now())
                """,
                (
                    target_pilot_key,
                    bool(source_margin.enabled),
                    float(source_margin.max_effective_leverage),
                    float(source_margin.minimum_free_capital),
                ),
            )

        # A new target starts from the observed Saxo state on its first runtime cycle.
        # No old cross or pending reversal is inherited or replayed.
        for table in (
            "pg_v2_autotrader_strategy_runtime_state",
            "pg_v2_autotrader_live_pilot_state",
            "pg_v2_autotrader_mtf_live_state",
            "pg_v2_autotrader_mtf_short_live_state",
            "pg_v2_autotrader_mtf_flip_live_state",
            "pg_v2_autotrader_fast_live_state",
        ):
            try:
                db.execute(f"DELETE FROM {table} WHERE pilot_key = ?", (target_pilot_key,))
            except Exception:
                # Optional strategy-specific state tables are created lazily by their
                # own runtime. Absence is equivalent to the desired no-replay state.
                pass

        db.execute(
            """
            INSERT INTO pg_v2_autotrader_strategy_switch_events(
                event_id, from_pilot_key, to_pilot_key, from_strategy_key,
                to_strategy_key, observed_direction, entry_mode, live_open_was_armed,
                settled_flat_provenance, provenance_kind, source_close_event_id,
                source_equity_at_switch, source_currency
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)
            """,
            (
                event_id,
                enrollment.pilot_key,
                target_pilot_key,
                enrollment.strategy_key,
                target.key,
                observed_direction,
                enrollment.entry_mode,
                bool(enrollment.live_open_armed),
                bool(flat_handoff),
                provenance_kind,
                float(source_equity.equity),
                source_equity.currency,
            ),
        )
        db.execute(
            """
            INSERT INTO pg_v2_autotrader_strategy_switch_marks(
                event_id, account_id, uic, asset_type, observed_direction,
                observed_net_position_id, observed_amount,
                observed_average_open_price, observed_mark_price, observed_pnl_pct
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                enrollment.account_id,
                int(enrollment.uic),
                enrollment.asset_type,
                observed_direction,
                None if observed is None else observed.net_position_id,
                None if observed is None else float(observed.amount),
                None if observed is None else float(observed.average_open_price),
                None if observed is None else float(observed.current_price),
                None if observed is None else float(observed.pnl_pct),
            ),
        )

    refreshed_old = load_strategy_enrollment_v2(enrollment.pilot_key)
    refreshed_target = load_strategy_enrollment_v2(target_pilot_key)
    if refreshed_old is None or refreshed_old.enabled:
        raise RuntimeError("source strategy pilot remained active after switch")
    if refreshed_target is None or not refreshed_target.enabled or refreshed_target.strategy_key != target.key:
        raise RuntimeError("target strategy pilot was not activated")
    if bool(refreshed_target.live_open_armed) != bool(enrollment.live_open_armed):
        raise RuntimeError("strategy switch failed to preserve LIVE OPEN arming policy")
    if refreshed_target.anchor_net_position_id != anchor:
        raise RuntimeError("strategy switch failed to preserve the observed Saxo position anchor")

    return StrategySwitchResultV2(
        from_pilot_key=enrollment.pilot_key,
        to_pilot_key=refreshed_target.pilot_key,
        from_strategy_key=enrollment.strategy_key,
        to_strategy_key=refreshed_target.strategy_key,
        observed_direction=observed_direction,
        entry_mode=refreshed_target.entry_mode,
        live_open_was_armed=enrollment.live_open_armed,
    )


__all__ = [
    "StrategySwitchResultV2",
    "ensure_hot_strategy_switch_schema_v2",
    "switch_live_strategy_v2",
]
