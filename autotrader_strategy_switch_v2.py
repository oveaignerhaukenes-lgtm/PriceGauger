from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from autotrader_entry_policy_v2 import load_pilot_margin_config_v2
from autotrader_mtf_live_runtime_v2 import ensure_mtf_live_schema_v2
from autotrader_mtf_short_live_runtime_v2 import ensure_mtf_short_live_schema_v2
from autotrader_pilot_equity_v2 import load_pilot_equity_v2
from autotrader_risk_control_v2 import _position_observations_v2
from autotrader_schema_v2 import ensure_autotrader_schema_v2
from autotrader_strategy_catalog_v2 import strategy_spec_v2
from autotrader_strategy_enrollment_v2 import (
    EXECUTION_MODE_LIVE,
    StrategyEnrollmentV2,
    load_strategy_enrollment_v2,
)
from autotrader_strategy_switch_provenance_v2 import (
    ensure_strategy_switch_provenance_schema_v2,
    require_source_settled_flat_provenance_v2,
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
    """Require exact LIVE FLAT and no working Saxo order for the product."""
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
        raise ValueError("strategy switch requires no working Saxo order for the product")


def _quiesce_source_open_authority_v2(enrollment: StrategyEnrollmentV2) -> None:
    """Fail-safe quiesce before external FLAT/order checks.

    If a later validation fails the source strategy remains active but OPEN is
    disarmed; the user may explicitly re-arm it. This is safer than leaving a race
    in which an old entry request can start while the switch is being validated.
    """
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
            SET live_open_armed = FALSE, updated_at = now()
            WHERE pilot_key = ? AND enabled = TRUE AND execution_mode = ?
            """,
            (enrollment.pilot_key, EXECUTION_MODE_LIVE),
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
    """Move a confirmed-FLAT LIVE product to a new canonical strategy pilot.

    The switch itself never places an order. Strategy identity remains canonical:
    each product+strategy pair keeps its own pilot key and clean P/L history. V1 only
    switches into a strategy pilot that has never been enrolled before; resuming an
    old strategy cohort is deliberately left for a later explicit lifecycle policy.

    Before the new cohort is created the source OPEN authority is quiesced, Saxo must
    report exact FLAT with no working order, and source close/P&L provenance must be
    fully settled. Equity -> enrollment -> Margin Envelope are created in one DB
    transaction in FK-safe order. The target receives an empty position anchor and
    remains LIVE-OPEN disarmed.
    """
    ensure_autotrader_schema_v2()
    ensure_mtf_live_schema_v2()
    ensure_mtf_short_live_schema_v2()
    ensure_strategy_switch_provenance_schema_v2()

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

    # Disarm/supersede before the external Saxo checks. Failure after this point is
    # deliberately fail-safe: the old pilot stays active but cannot originate OPEN.
    _quiesce_source_open_authority_v2(enrollment)
    _confirmed_flat_v2(enrollment)
    provenance = require_source_settled_flat_provenance_v2(enrollment)

    target_pilot_key = enrollment.product.pilot_key(target.key)
    target_existing = load_strategy_enrollment_v2(target_pilot_key)
    if target_existing is not None or _target_equity_state_exists_v2(target_pilot_key):
        raise ValueError(
            "target strategy pilot already has history or partial state; v1 strategy switch refuses to mix or resume cohorts"
        )

    source_equity = load_pilot_equity_v2(pilot_key=enrollment.pilot_key)
    source_margin = load_pilot_margin_config_v2(enrollment.pilot_key)
    event_id = str(uuid4())
    with connect() as db:
        # Repeat supersede inside the final control-plane transaction in case a
        # request was created between the initial quiesce and Saxo validation.
        db.execute(
            """
            UPDATE pg_v2_autotrader_execution_requests
            SET status = 'SUPERSEDED', block_reason = 'STRATEGY_SWITCH', updated_at = now()
            WHERE pilot_key = ? AND status IN ('PENDING', 'APPROVED')
            """,
            (enrollment.pilot_key,),
        )
        # Equity has no FK to enrollment; enrollment has the FK to equity. Create the
        # new clean cohort ledger first, inside this same transaction.
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
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, TRUE, FALSE, ?, now(), now())
            """,
            (
                target_pilot_key,
                target.key,
                EXECUTION_MODE_LIVE,
                enrollment.account_id,
                "",
                int(enrollment.uic),
                enrollment.asset_type,
                int(enrollment.market_id),
                int(enrollment.instrument_id),
                enrollment.market_name,
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
            INSERT INTO pg_v2_autotrader_strategy_switch_events(
                event_id, from_pilot_key, to_pilot_key, from_strategy_key,
                to_strategy_key, observed_direction, entry_mode, live_open_was_armed,
                settled_flat_provenance, provenance_kind, source_close_event_id,
                source_equity_at_switch, source_currency
            ) VALUES (?, ?, ?, ?, ?, 'FLAT', ?, ?, TRUE, ?, ?, ?, ?)
            """,
            (
                event_id,
                enrollment.pilot_key,
                target_pilot_key,
                enrollment.strategy_key,
                target.key,
                enrollment.entry_mode,
                bool(enrollment.live_open_armed),
                provenance.kind,
                provenance.source_close_event_id,
                float(source_equity.equity),
                source_equity.currency,
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
    if refreshed_target.anchor_net_position_id:
        raise RuntimeError("confirmed-FLAT target pilot must start without a position anchor")

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
