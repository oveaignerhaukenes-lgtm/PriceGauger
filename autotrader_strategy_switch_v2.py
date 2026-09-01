from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from autotrader_entry_policy_v2 import load_pilot_margin_config_v2, save_pilot_margin_config_v2
from autotrader_mtf_live_runtime_v2 import ensure_mtf_live_schema_v2
from autotrader_mtf_short_live_runtime_v2 import ensure_mtf_short_live_schema_v2
from autotrader_pilot_equity_v2 import initialize_pilot_equity_v2, load_pilot_equity_v2
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
    from_pilot_key: str
    to_pilot_key: str
    from_strategy_key: str
    to_strategy_key: str
    observed_direction: str
    entry_mode: str
    live_open_was_armed: bool


def _confirmed_flat_v2(enrollment: StrategyEnrollmentV2) -> None:
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
    if observations:
        side = observations[0].direction.strip().lower()
        observed = "LONG" if side == "buy" else "SHORT" if side == "sell" else side.upper()
        raise ValueError(
            "strategy switch requires confirmed FLAT exposure to keep strategy P/L attribution clean; "
            f"currently observed {observed}"
        )


def _prepare_target_capital_v2(
    enrollment: StrategyEnrollmentV2,
    *,
    target_pilot_key: str,
) -> None:
    """Seed a never-used target strategy from current settled controlled capital."""
    current = load_pilot_equity_v2(pilot_key=enrollment.pilot_key)
    initialize_pilot_equity_v2(
        pilot_key=target_pilot_key,
        seed_capital=float(current.equity),
        currency=current.currency,
    )

    source_margin = load_pilot_margin_config_v2(enrollment.pilot_key)
    if source_margin is not None:
        save_pilot_margin_config_v2(
            pilot_key=target_pilot_key,
            max_effective_leverage=float(source_margin.max_effective_leverage),
            minimum_free_capital=float(source_margin.minimum_free_capital),
            enabled=bool(source_margin.enabled),
        )


def switch_live_strategy_v2(
    *,
    pilot_key: str,
    target_strategy_key: str,
) -> StrategySwitchResultV2:
    """Move a confirmed-FLAT LIVE product to a new canonical strategy pilot.

    The switch itself never places an order. Strategy identity remains canonical:
    each product+strategy pair keeps its own pilot key and clean P/L history. V1 only
    switches into a strategy pilot that has never been enrolled before; resuming an
    old strategy cohort is deliberately left for a later explicit lifecycle policy.
    The current pilot becomes historical, the target starts with current settled
    controlled capital and copied Margin Envelope, and LIVE OPEN remains disarmed.
    Product Admission/sizing are product+direction contracts and are not duplicated.
    """
    ensure_autotrader_schema_v2()
    ensure_mtf_live_schema_v2()
    ensure_mtf_short_live_schema_v2()

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
            observed_direction="FLAT",
            entry_mode=enrollment.entry_mode,
            live_open_was_armed=enrollment.live_open_armed,
        )

    _confirmed_flat_v2(enrollment)
    target_pilot_key = enrollment.product.pilot_key(target.key)
    target_existing = load_strategy_enrollment_v2(target_pilot_key)
    if target_existing is not None:
        raise ValueError(
            "target strategy pilot already has history; v1 strategy switch refuses to mix or resume cohorts"
        )

    _prepare_target_capital_v2(enrollment, target_pilot_key=target_pilot_key)
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
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, TRUE, FALSE, ?, now(), now())
            """,
            (
                target_pilot_key,
                target.key,
                EXECUTION_MODE_LIVE,
                enrollment.account_id,
                enrollment.anchor_net_position_id,
                int(enrollment.uic),
                enrollment.asset_type,
                int(enrollment.market_id),
                int(enrollment.instrument_id),
                enrollment.market_name,
                enrollment.entry_mode,
            ),
        )
        # A new target should not have runtime rows, but clear defensively so the
        # contract remains no-replay if schema seeding ever changes later.
        db.execute(
            "DELETE FROM pg_v2_autotrader_strategy_runtime_state WHERE pilot_key = ?",
            (target_pilot_key,),
        )
        db.execute(
            "DELETE FROM pg_v2_autotrader_live_pilot_state WHERE pilot_key = ?",
            (target_pilot_key,),
        )
        db.execute(
            "DELETE FROM pg_v2_autotrader_mtf_live_state WHERE pilot_key = ?",
            (target_pilot_key,),
        )
        db.execute(
            "DELETE FROM pg_v2_autotrader_mtf_short_live_state WHERE pilot_key = ?",
            (target_pilot_key,),
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS pg_v2_autotrader_strategy_switch_events (
                event_id UUID PRIMARY KEY,
                from_pilot_key TEXT NOT NULL,
                to_pilot_key TEXT NOT NULL,
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
                event_id, from_pilot_key, to_pilot_key, from_strategy_key,
                to_strategy_key, observed_direction, entry_mode, live_open_was_armed
            ) VALUES (?, ?, ?, ?, ?, 'FLAT', ?, ?)
            """,
            (
                event_id,
                enrollment.pilot_key,
                target_pilot_key,
                enrollment.strategy_key,
                target.key,
                enrollment.entry_mode,
                bool(enrollment.live_open_armed),
            ),
        )

    refreshed_old = load_strategy_enrollment_v2(enrollment.pilot_key)
    refreshed_target = load_strategy_enrollment_v2(target_pilot_key)
    if refreshed_old is None or refreshed_old.enabled:
        raise RuntimeError("source strategy pilot remained active after switch")
    if refreshed_target is None or not refreshed_target.enabled or refreshed_target.strategy_key != target.key:
        raise RuntimeError("target strategy pilot was not activated")
    if refreshed_target.live_open_armed:
        raise RuntimeError("strategy switch must leave target LIVE OPEN disarmed")

    return StrategySwitchResultV2(
        from_pilot_key=enrollment.pilot_key,
        to_pilot_key=refreshed_target.pilot_key,
        from_strategy_key=enrollment.strategy_key,
        to_strategy_key=refreshed_target.strategy_key,
        observed_direction="FLAT",
        entry_mode=refreshed_target.entry_mode,
        live_open_was_armed=enrollment.live_open_armed,
    )


__all__ = ["StrategySwitchResultV2", "switch_live_strategy_v2"]
