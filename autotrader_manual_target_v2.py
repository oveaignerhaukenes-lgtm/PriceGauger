from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from autotrader_fast_live_runtime_v2 import (
    DIRECTION_FLAT,
    DIRECTION_LONG,
    DIRECTION_SHORT,
    FastLiveCycleV2,
    FastLiveStateV2,
    _exact_product_observation,
    _observed_direction,
    _persist_intent_and_request_v2,
    ensure_fast_live_schema_v2,
)
from autotrader_mtf_flip_live_runtime_v2 import ensure_mtf_flip_live_schema_v2
from autotrader_mtf_live_runtime_v2 import ensure_mtf_live_schema_v2
from autotrader_mtf_short_live_runtime_v2 import ensure_mtf_short_live_schema_v2
from autotrader_open_sizing_v2 import _extract_price, _info_price
from autotrader_pilot_equity_v2 import load_pilot_equity_v2
from autotrader_risk_control_v2 import PositionObservationV2, _position_observations_v2
from autotrader_schema_v2 import ensure_autotrader_schema_v2
from autotrader_strategy_enrollment_v2 import EXECUTION_MODE_LIVE, StrategyEnrollmentV2
from autotrader_strategy_switch_provenance_v2 import grant_user_confirmed_flat_authority_v2
from autotrader_strategy_switch_v2 import _pg_execution_inflight_v2, _quiesce_source_authority_v2
from database import connect
from saxo_provider import LIVE_BASE_URL, SaxoInstrument, configured_client


TARGET_PENDING = "PENDING"
TARGET_COMPLETE = "COMPLETE"
TARGET_SUPERSEDED = "SUPERSEDED"
TARGETS = {DIRECTION_LONG, DIRECTION_SHORT}


@dataclass(frozen=True, slots=True)
class ManualTargetStateV2:
    pilot_key: str
    strategy_key: str
    target_direction: str
    intent_event_id: str
    requested_at: datetime
    status: str


@dataclass(frozen=True, slots=True)
class ManualTargetRequestResultV2:
    pilot_key: str
    target_direction: str
    observed_direction: str
    request_created: bool
    already_observed: bool


@dataclass(frozen=True, slots=True)
class ManualTargetQuoteV2:
    bid: float
    ask: float


def _utc(value) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def ensure_manual_target_schema_v2() -> None:
    ensure_autotrader_schema_v2()
    ensure_fast_live_schema_v2()
    ensure_mtf_live_schema_v2()
    ensure_mtf_short_live_schema_v2()
    ensure_mtf_flip_live_schema_v2()
    with connect() as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS pg_v2_autotrader_manual_target_state (
                pilot_key TEXT PRIMARY KEY REFERENCES pg_v2_autotrader_strategy_enrollments(pilot_key),
                strategy_key TEXT NOT NULL,
                target_direction TEXT NOT NULL CHECK (target_direction IN ('LONG','SHORT')),
                intent_event_id UUID NOT NULL,
                requested_at TIMESTAMPTZ NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('PENDING','COMPLETE','SUPERSEDED')),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )


def load_manual_target_state_v2(pilot_key: str) -> ManualTargetStateV2 | None:
    ensure_manual_target_schema_v2()
    with connect() as db:
        row = db.execute(
            """
            SELECT pilot_key, strategy_key, target_direction, intent_event_id,
                   requested_at, status
            FROM pg_v2_autotrader_manual_target_state
            WHERE pilot_key = ?
            """,
            (str(pilot_key),),
        ).fetchone()
    if row is None:
        return None
    values = dict(row) if isinstance(row, dict) else {
        "pilot_key": row[0], "strategy_key": row[1], "target_direction": row[2],
        "intent_event_id": row[3], "requested_at": row[4], "status": row[5],
    }
    return ManualTargetStateV2(
        pilot_key=str(values["pilot_key"]),
        strategy_key=str(values["strategy_key"]),
        target_direction=str(values["target_direction"]),
        intent_event_id=str(values["intent_event_id"]),
        requested_at=_utc(values["requested_at"]),
        status=str(values["status"]),
    )


def manual_target_pending_v2(pilot_key: str) -> bool:
    state = load_manual_target_state_v2(pilot_key)
    return bool(state is not None and state.status == TARGET_PENDING)


def _save_target_state_v2(state: ManualTargetStateV2) -> None:
    with connect() as db:
        db.execute(
            """
            INSERT INTO pg_v2_autotrader_manual_target_state(
                pilot_key, strategy_key, target_direction, intent_event_id,
                requested_at, status, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, now())
            ON CONFLICT (pilot_key) DO UPDATE SET
                strategy_key=EXCLUDED.strategy_key,
                target_direction=EXCLUDED.target_direction,
                intent_event_id=EXCLUDED.intent_event_id,
                requested_at=EXCLUDED.requested_at,
                status=EXCLUDED.status,
                updated_at=now()
            """,
            (
                state.pilot_key, state.strategy_key, state.target_direction,
                state.intent_event_id, state.requested_at, state.status,
            ),
        )


def _runtime_intent_v2(state: ManualTargetStateV2, *, observed_direction: str) -> FastLiveStateV2:
    return FastLiveStateV2(
        pilot_key=state.pilot_key,
        strategy_key=state.strategy_key,
        desired_direction=state.target_direction,
        last_action_at=state.requested_at,
        pending_target_direction=None if observed_direction == state.target_direction else state.target_direction,
        intent_event_id=state.intent_event_id,
        intent_signal_at=state.requested_at,
        intent_signal=f"USER_TARGET_{state.target_direction}",
    )


def _reset_strategy_runtime_after_user_target_v2(pilot_key: str) -> None:
    """Force the selected strategy to bootstrap from the user-chosen exposure.

    A manual target is explicit user authority and supersedes old signal state. Deleting
    only runtime state (not ledger/history) ensures the next strategy evaluation adopts
    the actual Saxo exposure and does not resurrect a signal that predates the click.
    """
    ensure_manual_target_schema_v2()
    with connect() as db:
        for table in (
            "pg_v2_autotrader_strategy_runtime_state",
            "pg_v2_autotrader_live_pilot_state",
            "pg_v2_autotrader_fast_live_state",
            "pg_v2_autotrader_mtf_live_state",
            "pg_v2_autotrader_mtf_short_live_state",
            "pg_v2_autotrader_mtf_flip_live_state",
        ):
            db.execute(f"DELETE FROM {table} WHERE pilot_key = ?", (str(pilot_key),))


def load_manual_target_quote_v2(
    enrollment: StrategyEnrollmentV2,
    *,
    account_key: str,
) -> ManualTargetQuoteV2:
    client = configured_client()
    if client is None or client.base_url.rstrip("/").lower() != LIVE_BASE_URL.lower():
        raise RuntimeError("Saxo LIVE is required for executable target prices")
    instrument = SaxoInstrument(
        asset=enrollment.market_name,
        uic=int(enrollment.uic),
        asset_type=enrollment.asset_type,
    )
    payload = _info_price(
        client,
        account_key=str(account_key),
        instrument=instrument,
        amount=None,
        side="Buy",
    )
    return ManualTargetQuoteV2(
        bid=float(_extract_price(payload, "Sell")),
        ask=float(_extract_price(payload, "Buy")),
    )


def _live_observation_v2(enrollment: StrategyEnrollmentV2) -> tuple[PositionObservationV2 | None, str]:
    client = configured_client()
    if client is None or client.base_url.rstrip("/").lower() != LIVE_BASE_URL.lower():
        raise RuntimeError("Saxo LIVE is required for manual target")
    observed = _exact_product_observation(enrollment, _position_observations_v2(client))
    return observed, _observed_direction(observed)


def request_manual_target_v2(
    enrollment: StrategyEnrollmentV2,
    *,
    target_direction: str,
    now: datetime | None = None,
) -> ManualTargetRequestResultV2:
    """Request an explicit user LONG/SHORT target without POSTing from the web UI."""
    ensure_manual_target_schema_v2()
    if enrollment.execution_mode != EXECUTION_MODE_LIVE or not enrollment.enabled:
        raise ValueError("manual target requires an active LIVE AutoManager pilot")
    target = str(target_direction).strip().upper()
    if target not in TARGETS:
        raise ValueError("manual target must be LONG or SHORT")
    if _pg_execution_inflight_v2(enrollment):
        raise ValueError("vent til pågående PriceGauger/Saxo-ordre er ferdig")

    observed, observed_direction = _live_observation_v2(enrollment)
    requested_at = _utc(now or datetime.now(timezone.utc))
    event_id = str(uuid4())
    if observed_direction == target:
        state = ManualTargetStateV2(
            pilot_key=enrollment.pilot_key,
            strategy_key=enrollment.strategy_key,
            target_direction=target,
            intent_event_id=event_id,
            requested_at=requested_at,
            status=TARGET_COMPLETE,
        )
        _save_target_state_v2(state)
        _reset_strategy_runtime_after_user_target_v2(enrollment.pilot_key)
        return ManualTargetRequestResultV2(
            enrollment.pilot_key, target, observed_direction, False, True
        )

    # User target has precedence over any unstarted strategy request. Execution already
    # in SUBMITTING/accepted state was rejected above and is never cancelled here.
    _quiesce_source_authority_v2(enrollment)
    if observed_direction == DIRECTION_FLAT:
        grant_user_confirmed_flat_authority_v2(
            pilot_key=enrollment.pilot_key,
            source="TRADINGDESK_MANUAL_TARGET",
        )

    state = ManualTargetStateV2(
        pilot_key=enrollment.pilot_key,
        strategy_key=enrollment.strategy_key,
        target_direction=target,
        intent_event_id=event_id,
        requested_at=requested_at,
        status=TARGET_PENDING,
    )
    _save_target_state_v2(state)
    runtime = _runtime_intent_v2(state, observed_direction=observed_direction)
    equity = load_pilot_equity_v2(pilot_key=enrollment.pilot_key)
    created = _persist_intent_and_request_v2(
        enrollment=enrollment,
        state=runtime,
        observed=observed,
        observed_direction=observed_direction,
        budget_amount=equity.entry_budget,
        budget_currency=equity.currency,
        supersede_prior=True,
    )
    return ManualTargetRequestResultV2(
        enrollment.pilot_key, target, observed_direction, created, False
    )


def run_manual_target_once_v2(
    enrollment: StrategyEnrollmentV2,
    *,
    observations: tuple[PositionObservationV2, ...],
) -> FastLiveCycleV2 | None:
    """Continue one user target across CLOSE -> FLAT -> OPEN until observed."""
    state = load_manual_target_state_v2(enrollment.pilot_key)
    if state is None or state.status != TARGET_PENDING:
        return None
    if state.strategy_key != enrollment.strategy_key or not enrollment.enabled:
        _save_target_state_v2(
            ManualTargetStateV2(
                state.pilot_key, state.strategy_key, state.target_direction,
                state.intent_event_id, state.requested_at, TARGET_SUPERSEDED,
            )
        )
        return None

    observed = _exact_product_observation(enrollment, observations)
    observed_direction = _observed_direction(observed)
    if observed_direction == state.target_direction:
        _save_target_state_v2(
            ManualTargetStateV2(
                state.pilot_key, state.strategy_key, state.target_direction,
                state.intent_event_id, state.requested_at, TARGET_COMPLETE,
            )
        )
        _reset_strategy_runtime_after_user_target_v2(enrollment.pilot_key)
        return FastLiveCycleV2(
            enrollment.pilot_key, enrollment.strategy_key, state.target_direction,
            observed_direction, None, state.requested_at, True, False, False,
            "USER_TARGET_COMPLETE",
        )

    # If the position was flattened outside PG while this explicit target remained
    # pending, the user target itself is sufficient to grant a fresh one-shot FLAT
    # authority. LIVE OPEN still rechecks current Saxo FLAT immediately before POST.
    if observed_direction == DIRECTION_FLAT:
        grant_user_confirmed_flat_authority_v2(
            pilot_key=enrollment.pilot_key,
            source="TRADINGDESK_MANUAL_TARGET_CONTINUATION",
        )

    runtime = _runtime_intent_v2(state, observed_direction=observed_direction)
    equity = load_pilot_equity_v2(pilot_key=enrollment.pilot_key)
    created = _persist_intent_and_request_v2(
        enrollment=enrollment,
        state=runtime,
        observed=observed,
        observed_direction=observed_direction,
        budget_amount=equity.entry_budget,
        budget_currency=equity.currency,
        supersede_prior=False,
    )
    return FastLiveCycleV2(
        enrollment.pilot_key,
        enrollment.strategy_key,
        state.target_direction,
        observed_direction,
        state.target_direction,
        state.requested_at,
        True,
        created,
        False,
        f"USER_TARGET_{state.target_direction}",
    )


__all__ = [
    "ManualTargetQuoteV2",
    "ManualTargetRequestResultV2",
    "ManualTargetStateV2",
    "TARGET_COMPLETE",
    "TARGET_PENDING",
    "load_manual_target_quote_v2",
    "load_manual_target_state_v2",
    "manual_target_pending_v2",
    "request_manual_target_v2",
    "run_manual_target_once_v2",
]
