from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from autotrader_mtf_live_runtime_v2 import ensure_mtf_live_schema_v2
from autotrader_risk_control_v2 import _position_observations_v2
from autotrader_schema_v2 import ensure_autotrader_schema_v2
from autotrader_strategy_catalog_v2 import strategy_spec_v2
from autotrader_strategy_enrollment_v2 import (
    EXECUTION_MODE_LIVE,
    StrategyEnrollmentV2,
    load_strategy_enrollment_v2,
)
from database import connect
from saxo_provider import LIVE_BASE_URL, configured_client


@dataclass(frozen=True, slots=True)
class StrategySwitchResultV2:
    pilot_key: str
    from_strategy_key: str
    to_strategy_key: str
    observed_direction: str
    entry_mode: str
    live_open_was_armed: bool


def _observed_direction_v2(enrollment: StrategyEnrollmentV2) -> str:
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
    if not observations:
        return "FLAT"
    side = observations[0].direction.strip().lower()
    if side == "buy":
        return "LONG"
    if side == "sell":
        return "SHORT"
    raise RuntimeError(f"unsupported Saxo position direction: {observations[0].direction}")


def switch_live_strategy_v2(
    *,
    pilot_key: str,
    target_strategy_key: str,
) -> StrategySwitchResultV2:
    """Switch one active LIVE pilot to another strategy without placing an order.

    The pilot identity, settled equity ledger, Margin Envelope and direction-specific
    Product Admissions stay attached to the same pilot. Strategy changes are control-
    plane changes only: unstarted execution requests are superseded, LIVE OPEN is
    disarmed, and strategy runtime state is cleared so the target engine bootstraps
    from actual Saxo exposure rather than replaying stale signals.
    """
    ensure_autotrader_schema_v2()
    ensure_mtf_live_schema_v2()

    enrollment = load_strategy_enrollment_v2(str(pilot_key))
    if enrollment is None or not enrollment.enabled:
        raise LookupError("active AutoManager pilot not found")
    if enrollment.execution_mode != EXECUTION_MODE_LIVE:
        raise ValueError("only a LIVE AutoManager pilot can switch LIVE strategy")

    target = strategy_spec_v2(str(target_strategy_key))
    if target.key == enrollment.strategy_key:
        return StrategySwitchResultV2(
            pilot_key=enrollment.pilot_key,
            from_strategy_key=enrollment.strategy_key,
            to_strategy_key=target.key,
            observed_direction=_observed_direction_v2(enrollment),
            entry_mode=enrollment.entry_mode,
            live_open_was_armed=enrollment.live_open_armed,
        )

    observed_direction = _observed_direction_v2(enrollment)
    if observed_direction == "LONG" and not target.can_long:
        raise ValueError("target strategy cannot adopt the currently observed LONG exposure")
    if observed_direction == "SHORT" and not target.can_short:
        raise ValueError("target strategy cannot adopt the currently observed SHORT exposure")

    event_id = str(uuid4())
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
            UPDATE pg_v2_autotrader_strategy_enrollments
            SET strategy_key = ?, live_open_armed = FALSE, updated_at = now()
            WHERE pilot_key = ? AND enabled = TRUE AND execution_mode = ?
            """,
            (target.key, enrollment.pilot_key, EXECUTION_MODE_LIVE),
        )
        # Each strategy family persists its own cursor/planning state. Clear all
        # currently known LIVE state rows so the target strategy must bootstrap
        # from the actual Saxo exposure and latest closed bars; nothing is replayed.
        db.execute(
            "DELETE FROM pg_v2_autotrader_strategy_runtime_state WHERE pilot_key = ?",
            (enrollment.pilot_key,),
        )
        db.execute(
            "DELETE FROM pg_v2_autotrader_live_pilot_state WHERE pilot_key = ?",
            (enrollment.pilot_key,),
        )
        db.execute(
            "DELETE FROM pg_v2_autotrader_mtf_live_state WHERE pilot_key = ?",
            (enrollment.pilot_key,),
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS pg_v2_autotrader_strategy_switch_events (
                event_id UUID PRIMARY KEY,
                pilot_key TEXT NOT NULL,
                from_strategy_key TEXT NOT NULL,
                to_strategy_key TEXT NOT NULL,
                observed_direction TEXT NOT NULL,
                entry_mode TEXT NOT NULL,
                live_open_was_armed BOOLEAN NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        db.execute(
            """
            INSERT INTO pg_v2_autotrader_strategy_switch_events(
                event_id, pilot_key, from_strategy_key, to_strategy_key,
                observed_direction, entry_mode, live_open_was_armed
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                enrollment.pilot_key,
                enrollment.strategy_key,
                target.key,
                observed_direction,
                enrollment.entry_mode,
                bool(enrollment.live_open_armed),
            ),
        )

    refreshed = load_strategy_enrollment_v2(enrollment.pilot_key)
    if refreshed is None or not refreshed.enabled or refreshed.strategy_key != target.key:
        raise RuntimeError("strategy switch did not persist")
    if refreshed.live_open_armed:
        raise RuntimeError("strategy switch must leave LIVE OPEN disarmed")

    return StrategySwitchResultV2(
        pilot_key=refreshed.pilot_key,
        from_strategy_key=enrollment.strategy_key,
        to_strategy_key=refreshed.strategy_key,
        observed_direction=observed_direction,
        entry_mode=refreshed.entry_mode,
        live_open_was_armed=enrollment.live_open_armed,
    )


__all__ = ["StrategySwitchResultV2", "switch_live_strategy_v2"]
