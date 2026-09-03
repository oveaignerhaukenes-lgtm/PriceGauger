from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from autotrader_pilot_equity_v2 import load_pilot_equity_v2
from autotrader_risk_control_v2 import PositionObservationV2, _position_observations_v2
from autotrader_schema_v2 import ensure_autotrader_schema_v2
from autotrader_strategy_catalog_v2 import (
    MACD_1M_FLIP_STRATEGY_V2,
    STRONG_COCKTAIL_STRATEGY_V2,
)
from autotrader_strategy_enrollment_v2 import EXECUTION_MODE_LIVE, StrategyEnrollmentV2
from autotrader_strong_cocktail_shadow_v2 import (
    MAX_GAP_MINUTES,
    WARMUP_MINUTES,
    StrongCocktailEvidenceV1,
    _fast_evidence_by_action_v1,
    _load_cocktail_samples_v1,
    macd_1m_control_target_v1,
    strong_cocktail_target_v1,
)
from canonical_market_bars_v2 import CanonicalMarketBarStoreV2, CanonicalMarketBarV2
from database import connect
from saxo_provider import configured_client
from trading_desk import ChartBar
from trading_desk_indicators import calculate_indicators


DIRECTION_FLAT = "FLAT"
DIRECTION_LONG = "LONG"
DIRECTION_SHORT = "SHORT"
DIRECTIONS = {DIRECTION_FLAT, DIRECTION_LONG, DIRECTION_SHORT}
FAST_LIVE_STRATEGIES = {STRONG_COCKTAIL_STRATEGY_V2, MACD_1M_FLIP_STRATEGY_V2}
REQUEST_PENDING = "PENDING"
REQUEST_APPROVED = "APPROVED"
REQUEST_SUPERSEDED = "SUPERSEDED"
FRESH_MAX_AGE = timedelta(minutes=3)
HISTORY_MINUTES = max(360, WARMUP_MINUTES + 120)


@dataclass(frozen=True, slots=True)
class Macd1mClockV2:
    action_at: datetime
    previous_macd: float
    previous_signal: float
    previous_spread: float
    current_macd: float
    current_signal: float
    current_spread: float
    cross_direction: str | None
    data_gap: bool


@dataclass(frozen=True, slots=True)
class FastLiveStateV2:
    pilot_key: str
    strategy_key: str
    desired_direction: str
    last_action_at: datetime | None = None
    pending_target_direction: str | None = None
    intent_event_id: str | None = None
    intent_signal_at: datetime | None = None
    intent_signal: str | None = None
    intent_previous_macd: float | None = None
    intent_previous_signal: float | None = None
    intent_current_macd: float | None = None
    intent_current_signal: float | None = None


@dataclass(frozen=True, slots=True)
class FastLiveCycleV2:
    pilot_key: str
    strategy_key: str
    desired_direction: str
    observed_direction: str
    pending_target_direction: str | None
    action_at: datetime
    processed: bool
    request_created: bool
    bootstrap: bool
    reason: str


def _utc(value: Any) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _action_at(bar: CanonicalMarketBarV2) -> datetime:
    return _utc(bar.bar_time).replace(second=0, microsecond=0) + timedelta(minutes=1)


def _chart_bars(bars: tuple[CanonicalMarketBarV2, ...]) -> tuple[ChartBar, ...]:
    return tuple(
        ChartBar(
            market=str(item.market_name),
            bar_time=str(item.bar_time),
            open=float(item.open),
            high=float(item.high),
            low=float(item.low),
            close=float(item.close),
            volume=None if item.volume is None else float(item.volume),
        )
        for item in bars
    )


def _macd_1m_clock_v2(bars: tuple[CanonicalMarketBarV2, ...], *, now: datetime) -> Macd1mClockV2:
    eligible = tuple(item for item in bars if _action_at(item) <= now)
    if len(eligible) < 40:
        raise ValueError("fast LIVE needs enough canonical 1m history for MACD 12/26/9")
    indicators = calculate_indicators(_chart_bars(eligible), macd_fast=12, macd_slow=26, macd_signal=9)
    macd = {_utc(item.bar_time): float(item.value) for item in indicators.macd}
    signal = {_utc(item.bar_time): float(item.value) for item in indicators.macd_signal}

    current_bar = eligible[-1]
    previous_bar = eligible[-2]
    current_at = _utc(current_bar.bar_time)
    previous_at = _utc(previous_bar.bar_time)
    if current_at not in macd or current_at not in signal or previous_at not in macd or previous_at not in signal:
        raise ValueError("fast LIVE MACD signal warmup is incomplete")

    current_macd = macd[current_at]
    current_signal = signal[current_at]
    previous_macd = macd[previous_at]
    previous_signal = signal[previous_at]
    current_spread = current_macd - current_signal
    previous_spread = previous_macd - previous_signal
    action_at = _action_at(current_bar)
    previous_action_at = _action_at(previous_bar)
    gap_minutes = (action_at - previous_action_at).total_seconds() / 60.0
    data_gap = gap_minutes > float(MAX_GAP_MINUTES)
    cross = None
    if not data_gap:
        if previous_spread <= 0.0 < current_spread:
            cross = DIRECTION_LONG
        elif previous_spread >= 0.0 > current_spread:
            cross = DIRECTION_SHORT
    return Macd1mClockV2(
        action_at=action_at,
        previous_macd=float(previous_macd),
        previous_signal=float(previous_signal),
        previous_spread=float(previous_spread),
        current_macd=float(current_macd),
        current_signal=float(current_signal),
        current_spread=float(current_spread),
        cross_direction=cross,
        data_gap=bool(data_gap),
    )


def _latest_strong_evidence_v2(
    *,
    instrument_id: int,
    bars: tuple[CanonicalMarketBarV2, ...],
    action_at: datetime,
) -> StrongCocktailEvidenceV1 | None:
    samples = _load_cocktail_samples_v1(
        instrument_id=int(instrument_id),
        started_at=action_at - timedelta(minutes=30),
        as_of=action_at,
    )
    if not samples:
        return None
    evidence = _fast_evidence_by_action_v1(bars, samples)
    return evidence.get(action_at)


def ensure_fast_live_schema_v2() -> None:
    ensure_autotrader_schema_v2()
    with connect() as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS pg_v2_autotrader_fast_live_state (
                pilot_key TEXT PRIMARY KEY REFERENCES pg_v2_autotrader_strategy_enrollments(pilot_key),
                strategy_key TEXT NOT NULL,
                desired_direction TEXT NOT NULL CHECK (desired_direction IN ('FLAT','LONG','SHORT')),
                last_action_at TIMESTAMPTZ,
                pending_target_direction TEXT CHECK (pending_target_direction IN ('FLAT','LONG','SHORT')),
                intent_event_id UUID,
                intent_signal_at TIMESTAMPTZ,
                intent_signal TEXT,
                intent_previous_macd DOUBLE PRECISION,
                intent_previous_signal DOUBLE PRECISION,
                intent_current_macd DOUBLE PRECISION,
                intent_current_signal DOUBLE PRECISION,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )


def load_fast_live_state_v2(enrollment: StrategyEnrollmentV2) -> FastLiveStateV2 | None:
    ensure_fast_live_schema_v2()
    with connect() as db:
        row = db.execute(
            """
            SELECT strategy_key, desired_direction, last_action_at, pending_target_direction,
                   intent_event_id, intent_signal_at, intent_signal,
                   intent_previous_macd, intent_previous_signal,
                   intent_current_macd, intent_current_signal
            FROM pg_v2_autotrader_fast_live_state
            WHERE pilot_key = ?
            """,
            (enrollment.pilot_key,),
        ).fetchone()
    if row is None:
        return None
    values = dict(row) if isinstance(row, dict) else {
        "strategy_key": row[0], "desired_direction": row[1], "last_action_at": row[2],
        "pending_target_direction": row[3], "intent_event_id": row[4], "intent_signal_at": row[5],
        "intent_signal": row[6], "intent_previous_macd": row[7], "intent_previous_signal": row[8],
        "intent_current_macd": row[9], "intent_current_signal": row[10],
    }
    if str(values["strategy_key"]) != enrollment.strategy_key:
        raise ValueError("fast LIVE state strategy_key mismatch")
    return FastLiveStateV2(
        pilot_key=enrollment.pilot_key,
        strategy_key=enrollment.strategy_key,
        desired_direction=str(values["desired_direction"]),
        last_action_at=None if values["last_action_at"] is None else _utc(values["last_action_at"]),
        pending_target_direction=None if values["pending_target_direction"] is None else str(values["pending_target_direction"]),
        intent_event_id=None if values["intent_event_id"] is None else str(values["intent_event_id"]),
        intent_signal_at=None if values["intent_signal_at"] is None else _utc(values["intent_signal_at"]),
        intent_signal=None if values["intent_signal"] is None else str(values["intent_signal"]),
        intent_previous_macd=None if values["intent_previous_macd"] is None else float(values["intent_previous_macd"]),
        intent_previous_signal=None if values["intent_previous_signal"] is None else float(values["intent_previous_signal"]),
        intent_current_macd=None if values["intent_current_macd"] is None else float(values["intent_current_macd"]),
        intent_current_signal=None if values["intent_current_signal"] is None else float(values["intent_current_signal"]),
    )


def _persist_state_v2(state: FastLiveStateV2) -> None:
    if state.desired_direction not in DIRECTIONS:
        raise ValueError("invalid fast LIVE desired direction")
    if state.pending_target_direction is not None and state.pending_target_direction not in DIRECTIONS:
        raise ValueError("invalid fast LIVE pending target")
    with connect() as db:
        db.execute(
            """
            INSERT INTO pg_v2_autotrader_fast_live_state(
                pilot_key, strategy_key, desired_direction, last_action_at,
                pending_target_direction, intent_event_id, intent_signal_at, intent_signal,
                intent_previous_macd, intent_previous_signal, intent_current_macd,
                intent_current_signal, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, now())
            ON CONFLICT (pilot_key) DO UPDATE SET
                strategy_key=EXCLUDED.strategy_key,
                desired_direction=EXCLUDED.desired_direction,
                last_action_at=EXCLUDED.last_action_at,
                pending_target_direction=EXCLUDED.pending_target_direction,
                intent_event_id=EXCLUDED.intent_event_id,
                intent_signal_at=EXCLUDED.intent_signal_at,
                intent_signal=EXCLUDED.intent_signal,
                intent_previous_macd=EXCLUDED.intent_previous_macd,
                intent_previous_signal=EXCLUDED.intent_previous_signal,
                intent_current_macd=EXCLUDED.intent_current_macd,
                intent_current_signal=EXCLUDED.intent_current_signal,
                updated_at=now()
            """,
            (
                state.pilot_key, state.strategy_key, state.desired_direction, state.last_action_at,
                state.pending_target_direction, state.intent_event_id, state.intent_signal_at,
                state.intent_signal, state.intent_previous_macd, state.intent_previous_signal,
                state.intent_current_macd, state.intent_current_signal,
            ),
        )


def _exact_product_observation(
    enrollment: StrategyEnrollmentV2,
    observations: tuple[PositionObservationV2, ...],
) -> PositionObservationV2 | None:
    matches = tuple(
        item for item in observations
        if item.account_id == enrollment.account_id
        and int(item.uic) == int(enrollment.uic)
        and item.asset_type == enrollment.asset_type
    )
    if len(matches) > 1:
        raise RuntimeError("multiple Saxo positions match one fast LIVE product")
    return matches[0] if matches else None


def _observed_direction(observation: PositionObservationV2 | None) -> str:
    if observation is None:
        return DIRECTION_FLAT
    side = observation.direction.strip().lower()
    if side == "buy":
        return DIRECTION_LONG
    if side == "sell":
        return DIRECTION_SHORT
    raise ValueError(f"unsupported Saxo position direction: {observation.direction}")


def fast_request_action_v2(observed_direction: str, desired_direction: str) -> str | None:
    if observed_direction not in DIRECTIONS or desired_direction not in DIRECTIONS:
        raise ValueError("unsupported fast LIVE direction")
    if observed_direction == desired_direction:
        return None
    if observed_direction == DIRECTION_FLAT:
        return "OPEN" if desired_direction != DIRECTION_FLAT else None
    return "CLOSE"


def _supersede_prior_requests_v2(db, *, pilot_key: str, keep_request_id: str | None = None) -> None:
    if keep_request_id is None:
        db.execute(
            """
            UPDATE pg_v2_autotrader_execution_requests
            SET status = ?, block_reason = 'NEWER_FAST_SIGNAL', updated_at = now()
            WHERE pilot_key = ? AND status IN (?, ?)
            """,
            (REQUEST_SUPERSEDED, pilot_key, REQUEST_PENDING, REQUEST_APPROVED),
        )
        return
    db.execute(
        """
        UPDATE pg_v2_autotrader_execution_requests
        SET status = ?, block_reason = 'NEWER_FAST_SIGNAL', updated_at = now()
        WHERE pilot_key = ? AND status IN (?, ?) AND request_id <> ?
        """,
        (REQUEST_SUPERSEDED, pilot_key, REQUEST_PENDING, REQUEST_APPROVED, keep_request_id),
    )


def _signal_name_v2(
    *,
    strategy_key: str,
    target: str,
    clock: Macd1mClockV2,
    evidence: StrongCocktailEvidenceV1 | None,
) -> str:
    cross = clock.cross_direction
    if cross == DIRECTION_LONG:
        return "CROSS_UP"
    if cross == DIRECTION_SHORT:
        return "CROSS_DOWN"
    if strategy_key == STRONG_COCKTAIL_STRATEGY_V2:
        if target == DIRECTION_LONG:
            return "STRONG_LONG"
        if target == DIRECTION_SHORT:
            return "STRONG_SHORT"
        if evidence is not None and evidence.data_gap:
            return "DATA_GAP_FLAT"
        return "STRONG_FLAT"
    raise ValueError("1m MACD target changed without a MACD cross")


def _new_intent_state_v2(
    state: FastLiveStateV2,
    *,
    target: str,
    observed_direction: str,
    clock: Macd1mClockV2,
    signal: str,
) -> FastLiveStateV2:
    event_id = str(
        uuid5(
            NAMESPACE_URL,
            f"fast-live-intent|{state.pilot_key}|{state.strategy_key}|{clock.action_at.isoformat()}|{target}|{signal}",
        )
    )
    return replace(
        state,
        desired_direction=target,
        pending_target_direction=None if target == observed_direction else target,
        intent_event_id=event_id,
        intent_signal_at=clock.action_at,
        intent_signal=signal,
        intent_previous_macd=clock.previous_macd,
        intent_previous_signal=clock.previous_signal,
        intent_current_macd=clock.current_macd,
        intent_current_signal=clock.current_signal,
        last_action_at=clock.action_at,
    )


def _persist_bootstrap_v2(
    enrollment: StrategyEnrollmentV2,
    state: FastLiveStateV2,
    observed: PositionObservationV2 | None,
) -> None:
    with connect() as db:
        evaluation_id = str(uuid5(NAMESPACE_URL, f"fast-live-bootstrap|{enrollment.pilot_key}|{state.last_action_at}"))
        db.execute(
            """
            INSERT INTO pg_v2_autotrader_strategy_evaluations(
                evaluation_id, pilot_key, strategy_key, latest_closed_bar_time,
                observed_net_position_id, observed_direction, outcome_reason
            ) VALUES (?, ?, ?, ?, ?, ?, 'BOOTSTRAP_NO_REPLAY')
            ON CONFLICT (evaluation_id) DO NOTHING
            """,
            (
                evaluation_id, enrollment.pilot_key, enrollment.strategy_key,
                state.last_action_at,
                None if observed is None else observed.net_position_id,
                state.desired_direction,
            ),
        )


def _persist_intent_and_request_v2(
    *,
    enrollment: StrategyEnrollmentV2,
    state: FastLiveStateV2,
    observed: PositionObservationV2 | None,
    observed_direction: str,
    budget_amount: float,
    budget_currency: str,
    supersede_prior: bool,
) -> bool:
    if state.intent_event_id is None or state.intent_signal_at is None or state.intent_signal is None:
        return False
    desired = state.pending_target_direction or state.desired_direction
    request_action = fast_request_action_v2(observed_direction, desired)
    if request_action == "OPEN" and float(budget_amount) <= 0:
        request_action = None
        outcome = "FAST_ENTRY_BLOCKED_EQUITY_EXHAUSTED"
    elif request_action is None:
        outcome = "FAST_TARGET_ALREADY_OBSERVED"
    else:
        outcome = f"FAST_{request_action}_REQUESTED"

    evaluation_id = str(
        uuid5(
            NAMESPACE_URL,
            f"fast-live-evaluation|{state.intent_event_id}|{observed_direction}|{request_action or 'NO_ACTION'}",
        )
    )
    request_id = None
    if request_action is not None:
        request_id = str(
            uuid5(
                NAMESPACE_URL,
                f"fast-live-execution|{state.intent_event_id}|{request_action}|{desired}",
            )
        )

    with connect() as db:
        if supersede_prior:
            _supersede_prior_requests_v2(db, pilot_key=enrollment.pilot_key, keep_request_id=request_id)
        db.execute(
            """
            INSERT INTO pg_v2_autotrader_strategy_evaluations(
                evaluation_id, pilot_key, strategy_key, latest_closed_bar_time,
                observed_net_position_id, observed_direction, outcome_reason,
                intent_id, signal_at, signal, target_direction,
                previous_macd, previous_signal, current_macd, current_signal,
                requested_action, desired_direction, budget_amount, budget_currency,
                execution_request_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (evaluation_id) DO NOTHING
            """,
            (
                evaluation_id, enrollment.pilot_key, enrollment.strategy_key,
                state.last_action_at or state.intent_signal_at,
                None if observed is None else observed.net_position_id,
                observed_direction, outcome, state.intent_event_id, state.intent_signal_at,
                state.intent_signal, desired, state.intent_previous_macd,
                state.intent_previous_signal, state.intent_current_macd,
                state.intent_current_signal, request_action, desired,
                float(budget_amount), budget_currency, request_id,
            ),
        )
        if request_id is not None:
            db.execute(
                """
                INSERT INTO pg_v2_autotrader_execution_requests(
                    request_id, evaluation_id, pilot_key, strategy_key, action,
                    desired_direction, signal_at, signal, account_id,
                    observed_net_position_id, observed_direction, observed_amount,
                    observed_average_open_price, uic, asset_type, market_id,
                    instrument_id, budget_amount, budget_currency, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (request_id) DO NOTHING
                """,
                (
                    request_id, evaluation_id, enrollment.pilot_key, enrollment.strategy_key,
                    request_action, desired, state.intent_signal_at, state.intent_signal,
                    enrollment.account_id,
                    None if observed is None else observed.net_position_id,
                    observed_direction,
                    None if observed is None else observed.amount,
                    None if observed is None else observed.average_open_price,
                    enrollment.uic, enrollment.asset_type, enrollment.market_id,
                    enrollment.instrument_id, float(budget_amount), budget_currency,
                    REQUEST_PENDING,
                ),
            )
    return request_id is not None


def _clear_intent_v2(state: FastLiveStateV2, *, observed_direction: str) -> FastLiveStateV2:
    return replace(
        state,
        desired_direction=observed_direction,
        pending_target_direction=None,
        intent_event_id=None,
        intent_signal_at=None,
        intent_signal=None,
        intent_previous_macd=None,
        intent_previous_signal=None,
        intent_current_macd=None,
        intent_current_signal=None,
    )


def run_fast_live_strategy_once_v2(
    enrollment: StrategyEnrollmentV2,
    *,
    db_path: str = "pricegauger.db",
    now: datetime | None = None,
    observations: tuple[PositionObservationV2, ...] | None = None,
) -> FastLiveCycleV2:
    if enrollment.execution_mode != EXECUTION_MODE_LIVE or not enrollment.enabled:
        raise ValueError("fast runtime only executes active LIVE_MANAGE enrollments")
    if enrollment.strategy_key not in FAST_LIVE_STRATEGIES:
        raise ValueError("fast runtime received unsupported strategy")
    ensure_fast_live_schema_v2()

    end = _utc(now or datetime.now(timezone.utc))
    bars = CanonicalMarketBarStoreV2(db_path).load_instrument_range(
        instrument_id=int(enrollment.instrument_id),
        start=end - timedelta(minutes=HISTORY_MINUTES),
        end=end,
        limit=2_000,
    )
    if not bars:
        raise ValueError("fast LIVE has no exact canonical 1m history")
    materialized = tuple(bars)
    clock = _macd_1m_clock_v2(materialized, now=end)

    if observations is None:
        client = configured_client()
        if client is None:
            raise RuntimeError("Saxo client is not configured")
        observations = _position_observations_v2(client)
    observed = _exact_product_observation(enrollment, observations)
    observed_direction = _observed_direction(observed)

    state = load_fast_live_state_v2(enrollment)
    if state is None:
        state = FastLiveStateV2(
            pilot_key=enrollment.pilot_key,
            strategy_key=enrollment.strategy_key,
            desired_direction=observed_direction,
            last_action_at=clock.action_at,
        )
        _persist_state_v2(state)
        _persist_bootstrap_v2(enrollment, state, observed)
        return FastLiveCycleV2(
            enrollment.pilot_key, enrollment.strategy_key, state.desired_direction,
            observed_direction, None, clock.action_at, False, False, True,
            "BOOTSTRAP_NO_REPLAY",
        )

    # A strategy-origin transition remains authoritative only while it is explicitly
    # pending. Any unrelated manual/risk-origin exposure change is adopted instead of
    # reviving stale fast signals.
    if state.pending_target_direction is not None:
        if observed_direction == state.pending_target_direction:
            state = _clear_intent_v2(state, observed_direction=observed_direction)
            state = replace(state, last_action_at=state.last_action_at)
            _persist_state_v2(state)
    elif observed_direction != state.desired_direction:
        state = _clear_intent_v2(state, observed_direction=observed_direction)
        _persist_state_v2(state)

    new_action = state.last_action_at is None or clock.action_at > state.last_action_at
    evidence = None
    if new_action and enrollment.strategy_key == STRONG_COCKTAIL_STRATEGY_V2:
        evidence = _latest_strong_evidence_v2(
            instrument_id=enrollment.instrument_id,
            bars=materialized,
            action_at=clock.action_at,
        )
        if evidence is None:
            return FastLiveCycleV2(
                enrollment.pilot_key, enrollment.strategy_key, state.desired_direction,
                observed_direction, state.pending_target_direction, clock.action_at,
                False, False, False, "WAIT_STRONG_CONTEXT",
            )

    request_created = False
    reason = "NO_NEW_1M_ACTION"
    if new_action:
        fresh = timedelta(0) <= (end - clock.action_at) <= FRESH_MAX_AGE
        if not fresh:
            state = replace(state, last_action_at=clock.action_at)
            _persist_state_v2(state)
            reason = "STALE_1M_ACTION_SKIPPED"
        else:
            if enrollment.strategy_key == STRONG_COCKTAIL_STRATEGY_V2:
                assert evidence is not None
                target = strong_cocktail_target_v1(state.desired_direction, evidence)
            else:
                target = macd_1m_control_target_v1(
                    state.desired_direction,
                    cross_1m=clock.cross_direction,
                    data_gap=clock.data_gap,
                )
            if target != state.desired_direction:
                signal = _signal_name_v2(
                    strategy_key=enrollment.strategy_key,
                    target=target,
                    clock=clock,
                    evidence=evidence,
                )
                state = _new_intent_state_v2(
                    state,
                    target=target,
                    observed_direction=observed_direction,
                    clock=clock,
                    signal=signal,
                )
                equity = load_pilot_equity_v2(pilot_key=enrollment.pilot_key)
                request_created = _persist_intent_and_request_v2(
                    enrollment=enrollment,
                    state=state,
                    observed=observed,
                    observed_direction=observed_direction,
                    budget_amount=equity.entry_budget,
                    budget_currency=equity.currency,
                    supersede_prior=True,
                )
                reason = f"TARGET_{target}"
            else:
                state = replace(state, last_action_at=clock.action_at)
                _persist_state_v2(state)
                reason = "TARGET_UNCHANGED"

    # Continue a strategy-origin CLOSE -> observed FLAT -> OPEN chain without replaying
    # the underlying signal. All downstream OPEN gates still revalidate settlement,
    # Product Admission, current pilot equity, sizing and Saxo precheck.
    if state.pending_target_direction is not None and observed_direction != state.pending_target_direction:
        equity = load_pilot_equity_v2(pilot_key=enrollment.pilot_key)
        continued = _persist_intent_and_request_v2(
            enrollment=enrollment,
            state=state,
            observed=observed,
            observed_direction=observed_direction,
            budget_amount=equity.entry_budget,
            budget_currency=equity.currency,
            supersede_prior=False,
        )
        request_created = request_created or continued
        if not new_action:
            reason = "PENDING_TRANSITION_CONTINUED"

    _persist_state_v2(state)
    return FastLiveCycleV2(
        pilot_key=enrollment.pilot_key,
        strategy_key=enrollment.strategy_key,
        desired_direction=state.desired_direction,
        observed_direction=observed_direction,
        pending_target_direction=state.pending_target_direction,
        action_at=clock.action_at,
        processed=new_action,
        request_created=request_created,
        bootstrap=False,
        reason=reason,
    )


__all__ = [
    "FAST_LIVE_STRATEGIES",
    "FastLiveCycleV2",
    "FastLiveStateV2",
    "Macd1mClockV2",
    "ensure_fast_live_schema_v2",
    "fast_request_action_v2",
    "load_fast_live_state_v2",
    "run_fast_live_strategy_once_v2",
]
