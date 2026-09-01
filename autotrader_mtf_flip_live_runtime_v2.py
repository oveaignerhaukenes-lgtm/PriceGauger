from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from autotrader_mtf_entry_shadow_v2 import (
    ENTRY_TIMEFRAME_MINUTES,
    MtfObservationV2,
    REGIME_TIMEFRAME_MINUTES,
    VALIDATION_TIMEFRAME_MINUTES,
    closed_bars_v2,
    macd_observations_v2,
    regime_context_30m_v2,
)
from autotrader_mtf_flip_policy_v2 import (
    ACTION_CLOSE_FLAT,
    ACTION_CONFIRMATION,
    ACTION_FLIP_LONG,
    ACTION_FLIP_SHORT,
    ACTION_OPEN_LONG,
    ACTION_OPEN_SHORT,
    DIRECTION_FLAT,
    DIRECTION_LONG,
    DIRECTION_SHORT,
    LONG_STATES,
    MtfFlipDecisionV2,
    SHORT_STATES,
    STATE_CONFIRMED_30M_LONG,
    STATE_CONFIRMED_30M_SHORT,
    STATE_FLAT,
    cross_v2,
    mtf_flip_decision_v2,
)
from autotrader_mtf_short_policy_v2 import short_regime_context_30m_v2
from autotrader_pilot_equity_v2 import load_pilot_equity_v2
from autotrader_risk_control_v2 import PositionObservationV2, _position_observations_v2
from autotrader_schema_v2 import ensure_autotrader_schema_v2
from autotrader_strategy_catalog_v2 import MTF_LONG_SHORT_FLIP_STRATEGY_V2
from autotrader_strategy_enrollment_v2 import EXECUTION_MODE_LIVE, StrategyEnrollmentV2
from canonical_market_bars_v2 import CanonicalMarketBarStoreV2
from database import connect
from saxo_provider import configured_client


REQUEST_PENDING = "PENDING"
REQUEST_APPROVED = "APPROVED"
REQUEST_SUPERSEDED = "SUPERSEDED"
_TIMEFRAMES = (ENTRY_TIMEFRAME_MINUTES, VALIDATION_TIMEFRAME_MINUTES, REGIME_TIMEFRAME_MINUTES)
_PRIORITY = {REGIME_TIMEFRAME_MINUTES: 0, ENTRY_TIMEFRAME_MINUTES: 1, VALIDATION_TIMEFRAME_MINUTES: 2}
_ALLOWED_STATES = {STATE_FLAT, *LONG_STATES, *SHORT_STATES}


@dataclass(frozen=True, slots=True)
class MtfFlipPendingV2:
    event_id: str
    event_type: str
    signal_at: datetime
    signal: str
    target_direction: str
    previous_macd: float
    previous_signal: float
    current_macd: float
    current_signal: float


@dataclass(frozen=True, slots=True)
class MtfFlipLiveStateV2:
    pilot_key: str
    state: str
    last_5m_closed_at: datetime | None = None
    last_10m_closed_at: datetime | None = None
    last_30m_closed_at: datetime | None = None
    pending: MtfFlipPendingV2 | None = None


@dataclass(frozen=True, slots=True)
class MtfFlipLiveCycleV2:
    pilot_key: str
    state: str
    pending_target: str | None
    processed: int
    events: int
    requests: int
    bootstrap: bool


def _utc(value: Any) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _row_dict(row: Any) -> dict[str, Any]:
    return dict(row) if not isinstance(row, dict) else row


def ensure_mtf_flip_live_schema_v2() -> None:
    ensure_autotrader_schema_v2()
    with connect() as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS pg_v2_autotrader_mtf_flip_live_state (
                pilot_key TEXT PRIMARY KEY REFERENCES pg_v2_autotrader_strategy_enrollments(pilot_key),
                strategy_key TEXT NOT NULL,
                state TEXT NOT NULL CHECK (state IN (
                    'FLAT','PROVISIONAL_LONG','VALIDATED_10M_LONG','CONFIRMED_30M_LONG',
                    'PROVISIONAL_SHORT','VALIDATED_10M_SHORT','CONFIRMED_30M_SHORT'
                )),
                last_5m_closed_at TIMESTAMPTZ,
                last_10m_closed_at TIMESTAMPTZ,
                last_30m_closed_at TIMESTAMPTZ,
                pending_event_id UUID,
                pending_event_type TEXT,
                pending_signal_at TIMESTAMPTZ,
                pending_signal TEXT,
                pending_target_direction TEXT CHECK (pending_target_direction IN ('LONG','SHORT')),
                pending_previous_macd DOUBLE PRECISION,
                pending_previous_signal DOUBLE PRECISION,
                pending_current_macd DOUBLE PRECISION,
                pending_current_signal DOUBLE PRECISION,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS pg_v2_autotrader_mtf_flip_live_events (
                event_id UUID PRIMARY KEY,
                pilot_key TEXT NOT NULL REFERENCES pg_v2_autotrader_strategy_enrollments(pilot_key),
                event_type TEXT NOT NULL,
                action TEXT NOT NULL,
                action_at TIMESTAMPTZ NOT NULL,
                price DOUBLE PRECISION NOT NULL,
                prior_state TEXT NOT NULL,
                desired_state TEXT NOT NULL,
                desired_direction TEXT,
                carry_reversal BOOLEAN NOT NULL,
                reason TEXT NOT NULL,
                long_context_30m TEXT NOT NULL,
                short_context_30m TEXT NOT NULL,
                spread_5m DOUBLE PRECISION,
                spread_10m DOUBLE PRECISION,
                spread_30m DOUBLE PRECISION,
                execution_request_id UUID,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE(pilot_key, event_type, action_at)
            )
            """
        )


def load_mtf_flip_live_state_v2(pilot_key: str) -> MtfFlipLiveStateV2 | None:
    ensure_mtf_flip_live_schema_v2()
    with connect() as db:
        row = db.execute(
            """
            SELECT state, last_5m_closed_at, last_10m_closed_at, last_30m_closed_at,
                   pending_event_id, pending_event_type, pending_signal_at, pending_signal,
                   pending_target_direction, pending_previous_macd, pending_previous_signal,
                   pending_current_macd, pending_current_signal
            FROM pg_v2_autotrader_mtf_flip_live_state
            WHERE pilot_key = ? AND strategy_key = ?
            """,
            (str(pilot_key), MTF_LONG_SHORT_FLIP_STRATEGY_V2),
        ).fetchone()
    if row is None:
        return None
    item = _row_dict(row)
    pending = None
    if item["pending_event_id"] is not None:
        pending = MtfFlipPendingV2(
            event_id=str(item["pending_event_id"]),
            event_type=str(item["pending_event_type"]),
            signal_at=_utc(item["pending_signal_at"]),
            signal=str(item["pending_signal"]),
            target_direction=str(item["pending_target_direction"]),
            previous_macd=float(item["pending_previous_macd"]),
            previous_signal=float(item["pending_previous_signal"]),
            current_macd=float(item["pending_current_macd"]),
            current_signal=float(item["pending_current_signal"]),
        )
    return MtfFlipLiveStateV2(
        pilot_key=str(pilot_key),
        state=str(item["state"]),
        last_5m_closed_at=None if item["last_5m_closed_at"] is None else _utc(item["last_5m_closed_at"]),
        last_10m_closed_at=None if item["last_10m_closed_at"] is None else _utc(item["last_10m_closed_at"]),
        last_30m_closed_at=None if item["last_30m_closed_at"] is None else _utc(item["last_30m_closed_at"]),
        pending=pending,
    )


def _persist_state_v2(state: MtfFlipLiveStateV2) -> None:
    if state.state not in _ALLOWED_STATES:
        raise ValueError(f"invalid MTF flip state: {state.state}")
    pending = state.pending
    with connect() as db:
        db.execute(
            """
            INSERT INTO pg_v2_autotrader_mtf_flip_live_state(
                pilot_key, strategy_key, state, last_5m_closed_at, last_10m_closed_at,
                last_30m_closed_at, pending_event_id, pending_event_type, pending_signal_at,
                pending_signal, pending_target_direction, pending_previous_macd,
                pending_previous_signal, pending_current_macd, pending_current_signal, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, now())
            ON CONFLICT (pilot_key) DO UPDATE SET
                strategy_key=EXCLUDED.strategy_key,
                state=EXCLUDED.state,
                last_5m_closed_at=EXCLUDED.last_5m_closed_at,
                last_10m_closed_at=EXCLUDED.last_10m_closed_at,
                last_30m_closed_at=EXCLUDED.last_30m_closed_at,
                pending_event_id=EXCLUDED.pending_event_id,
                pending_event_type=EXCLUDED.pending_event_type,
                pending_signal_at=EXCLUDED.pending_signal_at,
                pending_signal=EXCLUDED.pending_signal,
                pending_target_direction=EXCLUDED.pending_target_direction,
                pending_previous_macd=EXCLUDED.pending_previous_macd,
                pending_previous_signal=EXCLUDED.pending_previous_signal,
                pending_current_macd=EXCLUDED.pending_current_macd,
                pending_current_signal=EXCLUDED.pending_current_signal,
                updated_at=now()
            """,
            (
                state.pilot_key,
                MTF_LONG_SHORT_FLIP_STRATEGY_V2,
                state.state,
                state.last_5m_closed_at,
                state.last_10m_closed_at,
                state.last_30m_closed_at,
                None if pending is None else pending.event_id,
                None if pending is None else pending.event_type,
                None if pending is None else pending.signal_at,
                None if pending is None else pending.signal,
                None if pending is None else pending.target_direction,
                None if pending is None else pending.previous_macd,
                None if pending is None else pending.previous_signal,
                None if pending is None else pending.current_macd,
                None if pending is None else pending.current_signal,
            ),
        )


def _exact_product_observation(
    enrollment: StrategyEnrollmentV2,
    observations: tuple[PositionObservationV2, ...],
) -> PositionObservationV2 | None:
    matches = tuple(
        item
        for item in observations
        if item.account_id == enrollment.account_id
        and int(item.uic) == int(enrollment.uic)
        and item.asset_type == enrollment.asset_type
    )
    if len(matches) > 1:
        raise RuntimeError("multiple Saxo positions match one MTF flip LIVE product")
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


def _confirmed_state(direction: str) -> str:
    if direction == DIRECTION_LONG:
        return STATE_CONFIRMED_30M_LONG
    if direction == DIRECTION_SHORT:
        return STATE_CONFIRMED_30M_SHORT
    if direction == DIRECTION_FLAT:
        return STATE_FLAT
    raise ValueError(f"unsupported direction: {direction}")


def _reconcile_state_to_observed_v2(
    state: MtfFlipLiveStateV2,
    observed_direction: str,
) -> MtfFlipLiveStateV2:
    pending = state.pending
    if pending is not None:
        if observed_direction == pending.target_direction:
            return replace(state, state=_confirmed_state(observed_direction), pending=None)
        return replace(state, state=STATE_FLAT)

    expected = (
        DIRECTION_LONG if state.state in LONG_STATES
        else DIRECTION_SHORT if state.state in SHORT_STATES
        else DIRECTION_FLAT
    )
    if expected == observed_direction:
        return state
    # Manual/risk/external exposure changes are adopted as observation only. No old
    # MTF regime is replayed into an order when Saxo and strategy state diverge.
    return replace(state, state=_confirmed_state(observed_direction), pending=None)


def _latest_at(items: tuple[MtfObservationV2, ...], at: datetime) -> MtfObservationV2 | None:
    latest = None
    for item in items:
        if item.closed_at > at:
            break
        latest = item
    return latest


def _latest_pair_at(
    items: tuple[MtfObservationV2, ...], at: datetime
) -> tuple[MtfObservationV2 | None, MtfObservationV2 | None]:
    eligible = [item for item in items if item.closed_at <= at]
    if len(eligible) < 2:
        return None, eligible[-1] if eligible else None
    return eligible[-2], eligible[-1]


def _cursor(state: MtfFlipLiveStateV2, timeframe: int) -> datetime | None:
    return {
        ENTRY_TIMEFRAME_MINUTES: state.last_5m_closed_at,
        VALIDATION_TIMEFRAME_MINUTES: state.last_10m_closed_at,
        REGIME_TIMEFRAME_MINUTES: state.last_30m_closed_at,
    }[int(timeframe)]


def _advance_cursor(state: MtfFlipLiveStateV2, observation: MtfObservationV2) -> MtfFlipLiveStateV2:
    updates = {
        ENTRY_TIMEFRAME_MINUTES: {"last_5m_closed_at": observation.closed_at},
        VALIDATION_TIMEFRAME_MINUTES: {"last_10m_closed_at": observation.closed_at},
        REGIME_TIMEFRAME_MINUTES: {"last_30m_closed_at": observation.closed_at},
    }[observation.timeframe_minutes]
    return replace(state, **updates)


def _latest_work(
    state: MtfFlipLiveStateV2,
    observations: dict[int, tuple[MtfObservationV2, ...]],
    *,
    now: datetime,
) -> tuple[tuple[int, MtfObservationV2, MtfObservationV2, bool], ...]:
    work: list[tuple[datetime, int, int, MtfObservationV2, MtfObservationV2, bool]] = []
    for timeframe, items in observations.items():
        if len(items) < 2:
            continue
        previous, current = items[-2], items[-1]
        cursor = _cursor(state, timeframe)
        if cursor is not None and current.closed_at <= cursor:
            continue
        max_age = timedelta(minutes=int(timeframe) + 2)
        fresh = timedelta(0) <= (now - current.closed_at) <= max_age
        work.append((current.closed_at, _PRIORITY[timeframe], timeframe, previous, current, fresh))
    work.sort(key=lambda item: (item[0], item[1]))
    return tuple((tf, previous, current, fresh) for _, _, tf, previous, current, fresh in work)


def _signal_for_decision(decision: MtfFlipDecisionV2) -> str | None:
    if decision.action in {ACTION_OPEN_LONG, ACTION_FLIP_LONG}:
        return "CROSS_UP"
    if decision.action in {ACTION_OPEN_SHORT, ACTION_FLIP_SHORT}:
        return "CROSS_DOWN"
    if decision.action == ACTION_CLOSE_FLAT:
        return "CROSS_DOWN" if "LONG" in decision.event_type else "CROSS_UP"
    if decision.action == ACTION_CONFIRMATION:
        return None
    raise ValueError(f"unsupported MTF flip action: {decision.action}")


def _request_action(observed_direction: str, desired_direction: str | None) -> str | None:
    if desired_direction is None:
        return None
    if desired_direction == DIRECTION_FLAT:
        return "CLOSE" if observed_direction != DIRECTION_FLAT else None
    if observed_direction == desired_direction:
        return None
    if observed_direction == DIRECTION_FLAT:
        return "OPEN"
    return "CLOSE"


def _event_id(enrollment: StrategyEnrollmentV2, decision: MtfFlipDecisionV2, current: MtfObservationV2) -> str:
    return str(
        uuid5(
            NAMESPACE_URL,
            f"mtf-flip-event|{enrollment.pilot_key}|{decision.event_type}|{current.closed_at.isoformat()}",
        )
    )


def _pending_from_decision(
    *,
    event_id: str,
    decision: MtfFlipDecisionV2,
    previous: MtfObservationV2,
    current: MtfObservationV2,
) -> MtfFlipPendingV2:
    signal = _signal_for_decision(decision)
    if not decision.carry_reversal or signal is None or decision.desired_direction not in {DIRECTION_LONG, DIRECTION_SHORT}:
        raise ValueError("only a directional carried reversal can become pending")
    return MtfFlipPendingV2(
        event_id=event_id,
        event_type=decision.event_type,
        signal_at=current.closed_at,
        signal=signal,
        target_direction=decision.desired_direction,
        previous_macd=float(previous.macd),
        previous_signal=float(previous.signal),
        current_macd=float(current.macd),
        current_signal=float(current.signal),
    )


def _persist_event_and_request_v2(
    *,
    enrollment: StrategyEnrollmentV2,
    state_before: MtfFlipLiveStateV2,
    decision: MtfFlipDecisionV2,
    previous: MtfObservationV2,
    current: MtfObservationV2,
    long_context_30m: str,
    short_context_30m: str,
    latest_5m: MtfObservationV2 | None,
    latest_10m: MtfObservationV2 | None,
    latest_30m: MtfObservationV2 | None,
    observed: PositionObservationV2 | None,
    budget_amount: float,
    budget_currency: str,
    event_id_override: str | None = None,
) -> bool:
    observed_direction = _observed_direction(observed)
    desired_direction = decision.desired_direction
    request_action = _request_action(observed_direction, desired_direction)
    if request_action == "OPEN" and float(budget_amount) <= 0:
        request_action = None
        outcome = "MTF_FLIP_ENTRY_BLOCKED_EQUITY_EXHAUSTED"
    elif desired_direction is None:
        outcome = f"MTF_FLIP_{decision.event_type}"
    elif request_action is None:
        outcome = "MTF_FLIP_TARGET_ALREADY_OBSERVED"
    else:
        outcome = f"MTF_FLIP_{decision.event_type}_{request_action}_REQUESTED"

    signal = _signal_for_decision(decision)
    event_id = event_id_override or _event_id(enrollment, decision, current)
    evaluation_id = str(
        uuid5(
            NAMESPACE_URL,
            "|".join(
                (
                    "mtf-flip-evaluation",
                    event_id,
                    current.closed_at.isoformat(),
                    observed_direction,
                    request_action or "NO_ACTION",
                )
            ),
        )
    )
    request_id = None
    if request_action is not None and signal is not None:
        request_id = str(
            uuid5(
                NAMESPACE_URL,
                f"mtf-flip-execution|{event_id}|{request_action}|{desired_direction}",
            )
        )

    with connect() as db:
        if signal is not None:
            db.execute(
                """
                UPDATE pg_v2_autotrader_execution_requests
                SET status = ?, block_reason = 'NEWER_MTF_FLIP_SIGNAL', updated_at = now()
                WHERE pilot_key = ? AND status IN (?, ?)
                  AND (? IS NULL OR request_id <> ?)
                """,
                (
                    REQUEST_SUPERSEDED,
                    enrollment.pilot_key,
                    REQUEST_PENDING,
                    REQUEST_APPROVED,
                    request_id,
                    request_id,
                ),
            )

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
                evaluation_id,
                enrollment.pilot_key,
                enrollment.strategy_key,
                current.closed_at,
                None if observed is None else observed.net_position_id,
                observed_direction,
                outcome,
                event_id if signal is not None else None,
                current.closed_at if signal is not None else None,
                signal,
                desired_direction,
                float(previous.macd),
                float(previous.signal),
                float(current.macd),
                float(current.signal),
                request_action,
                desired_direction,
                float(budget_amount),
                budget_currency,
                request_id,
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
                    request_id,
                    evaluation_id,
                    enrollment.pilot_key,
                    enrollment.strategy_key,
                    request_action,
                    desired_direction,
                    current.closed_at,
                    signal,
                    enrollment.account_id,
                    None if observed is None else observed.net_position_id,
                    observed_direction,
                    None if observed is None else observed.amount,
                    None if observed is None else observed.average_open_price,
                    enrollment.uic,
                    enrollment.asset_type,
                    enrollment.market_id,
                    enrollment.instrument_id,
                    float(budget_amount),
                    budget_currency,
                    REQUEST_PENDING,
                ),
            )

        db.execute(
            """
            INSERT INTO pg_v2_autotrader_mtf_flip_live_events(
                event_id, pilot_key, event_type, action, action_at, price,
                prior_state, desired_state, desired_direction, carry_reversal,
                reason, long_context_30m, short_context_30m,
                spread_5m, spread_10m, spread_30m, execution_request_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (event_id) DO NOTHING
            """,
            (
                event_id,
                enrollment.pilot_key,
                decision.event_type,
                decision.action,
                current.closed_at,
                float(current.close),
                state_before.state,
                decision.desired_state,
                desired_direction,
                bool(decision.carry_reversal),
                decision.reason,
                long_context_30m,
                short_context_30m,
                None if latest_5m is None else float(latest_5m.spread),
                None if latest_10m is None else float(latest_10m.spread),
                None if latest_30m is None else float(latest_30m.spread),
                request_id,
            ),
        )
    return request_id is not None


def _bootstrap_state_v2(
    *,
    enrollment: StrategyEnrollmentV2,
    observed: PositionObservationV2 | None,
    observations: dict[int, tuple[MtfObservationV2, ...]],
) -> MtfFlipLiveStateV2:
    direction = _observed_direction(observed)
    state = MtfFlipLiveStateV2(
        pilot_key=enrollment.pilot_key,
        state=_confirmed_state(direction),
        last_5m_closed_at=observations[ENTRY_TIMEFRAME_MINUTES][-1].closed_at,
        last_10m_closed_at=observations[VALIDATION_TIMEFRAME_MINUTES][-1].closed_at,
        last_30m_closed_at=observations[REGIME_TIMEFRAME_MINUTES][-1].closed_at,
        pending=None,
    )
    _persist_state_v2(state)
    latest = max(item[-1].closed_at for item in observations.values())
    with connect() as db:
        evaluation_id = str(uuid5(NAMESPACE_URL, f"mtf-flip-bootstrap|{enrollment.pilot_key}|{latest.isoformat()}"))
        db.execute(
            """
            INSERT INTO pg_v2_autotrader_strategy_evaluations(
                evaluation_id, pilot_key, strategy_key, latest_closed_bar_time,
                observed_net_position_id, observed_direction, outcome_reason
            ) VALUES (?, ?, ?, ?, ?, ?, 'BOOTSTRAP_NO_REPLAY')
            ON CONFLICT (evaluation_id) DO NOTHING
            """,
            (
                evaluation_id,
                enrollment.pilot_key,
                enrollment.strategy_key,
                latest,
                None if observed is None else observed.net_position_id,
                direction,
            ),
        )
    return state


def _pending_decision(pending: MtfFlipPendingV2) -> MtfFlipDecisionV2:
    action = ACTION_FLIP_LONG if pending.target_direction == DIRECTION_LONG else ACTION_FLIP_SHORT
    return MtfFlipDecisionV2(
        event_type=pending.event_type,
        action=action,
        desired_state=STATE_FLAT,
        desired_direction=pending.target_direction,
        carry_reversal=True,
        reason="continue immutable closed-30m reversal intent after confirmed exposure transition",
    )


def run_mtf_flip_live_strategy_once_v2(
    enrollment: StrategyEnrollmentV2,
    *,
    db_path: str = "pricegauger.db",
    now: datetime | None = None,
    observations: tuple[PositionObservationV2, ...] | None = None,
) -> MtfFlipLiveCycleV2:
    if enrollment.execution_mode != EXECUTION_MODE_LIVE or not enrollment.enabled:
        raise ValueError("MTF flip runtime only executes active LIVE_MANAGE enrollments")
    if enrollment.strategy_key != MTF_LONG_SHORT_FLIP_STRATEGY_V2:
        raise ValueError("MTF flip runtime received a non-MTF-flip strategy")
    ensure_mtf_flip_live_schema_v2()

    end = _utc(now or datetime.now(timezone.utc))
    start = end - timedelta(days=14)
    bars = CanonicalMarketBarStoreV2(db_path).load_instrument_range(
        instrument_id=enrollment.instrument_id,
        start=start,
        end=end,
        limit=100_000,
    )
    points = tuple(item.point for item in bars)
    if not points:
        raise ValueError("MTF flip LIVE has no exact canonical 1m history")

    by_tf: dict[int, tuple[MtfObservationV2, ...]] = {}
    for timeframe in _TIMEFRAMES:
        closed = closed_bars_v2(points, market=enrollment.market_name, timeframe_minutes=timeframe)
        items = macd_observations_v2(closed, timeframe_minutes=timeframe)
        if len(items) < 2:
            raise ValueError(f"MTF flip LIVE needs enough closed {timeframe}m bars for MACD 12/26/9")
        by_tf[timeframe] = items

    if observations is None:
        client = configured_client()
        if client is None:
            raise RuntimeError("Saxo client is not configured")
        observations = _position_observations_v2(client)
    observed = _exact_product_observation(enrollment, observations)
    observed_direction = _observed_direction(observed)

    state = load_mtf_flip_live_state_v2(enrollment.pilot_key)
    if state is None:
        state = _bootstrap_state_v2(enrollment=enrollment, observed=observed, observations=by_tf)
        return MtfFlipLiveCycleV2(enrollment.pilot_key, state.state, None, 0, 0, 0, True)

    reconciled = _reconcile_state_to_observed_v2(state, observed_direction)
    if reconciled != state:
        state = reconciled
        _persist_state_v2(state)

    equity = load_pilot_equity_v2(pilot_key=enrollment.pilot_key)
    processed = 0
    event_count = 0
    request_count = 0

    for timeframe, previous, current, fresh in _latest_work(state, by_tf, now=end):
        processed += 1
        state_before = state
        state = _advance_cursor(state, current)
        if not fresh:
            _persist_state_v2(state)
            continue

        previous_30m, latest_30m = _latest_pair_at(by_tf[REGIME_TIMEFRAME_MINUTES], current.closed_at)
        long_context = regime_context_30m_v2(previous_30m, latest_30m)
        short_context = short_regime_context_30m_v2(previous_30m, latest_30m)
        latest_5m = _latest_at(by_tf[ENTRY_TIMEFRAME_MINUTES], current.closed_at)
        latest_10m = _latest_at(by_tf[VALIDATION_TIMEFRAME_MINUTES], current.closed_at)

        # While an opposite leg is pending, only a newer closed 30m cross may alter
        # that carried reversal. Fast clocks advance but cannot create a second order
        # path or turn transient noise into another flip.
        if state.pending is not None:
            if timeframe == REGIME_TIMEFRAME_MINUTES:
                crossing = cross_v2(previous, current)
                new_target = DIRECTION_LONG if crossing == "CROSS_UP" else DIRECTION_SHORT if crossing == "CROSS_DOWN" else None
                if new_target is not None and current.closed_at > state.pending.signal_at and new_target != state.pending.target_direction:
                    if observed_direction == new_target:
                        state = replace(state, state=_confirmed_state(new_target), pending=None)
                    else:
                        event_type = "FLIP_30M_TO_LONG" if new_target == DIRECTION_LONG else "FLIP_30M_TO_SHORT"
                        action = ACTION_FLIP_LONG if new_target == DIRECTION_LONG else ACTION_FLIP_SHORT
                        replacement = MtfFlipDecisionV2(
                            event_type=event_type,
                            action=action,
                            desired_state=STATE_FLAT,
                            desired_direction=new_target,
                            carry_reversal=True,
                            reason="newer closed 30m cross supersedes the prior pending MTF reversal",
                        )
                        replacement_event_id = _event_id(enrollment, replacement, current)
                        state = replace(
                            state,
                            state=STATE_FLAT,
                            pending=_pending_from_decision(
                                event_id=replacement_event_id,
                                decision=replacement,
                                previous=previous,
                                current=current,
                            ),
                        )
                        event_count += 1
                        if _persist_event_and_request_v2(
                            enrollment=enrollment,
                            state_before=state_before,
                            decision=replacement,
                            previous=previous,
                            current=current,
                            long_context_30m=long_context,
                            short_context_30m=short_context,
                            latest_5m=latest_5m,
                            latest_10m=latest_10m,
                            latest_30m=latest_30m,
                            observed=observed,
                            budget_amount=equity.entry_budget,
                            budget_currency=equity.currency,
                            event_id_override=replacement_event_id,
                        ):
                            request_count += 1
            _persist_state_v2(state)
            continue

        decision = mtf_flip_decision_v2(
            state=state.state,
            timeframe_minutes=timeframe,
            previous=previous,
            current=current,
            long_context_30m=long_context,
            short_context_30m=short_context,
        )
        if decision is None:
            _persist_state_v2(state)
            continue

        event_count += 1
        event_id = _event_id(enrollment, decision, current)
        if _persist_event_and_request_v2(
            enrollment=enrollment,
            state_before=state_before,
            decision=decision,
            previous=previous,
            current=current,
            long_context_30m=long_context,
            short_context_30m=short_context,
            latest_5m=latest_5m,
            latest_10m=latest_10m,
            latest_30m=latest_30m,
            observed=observed,
            budget_amount=equity.entry_budget,
            budget_currency=equity.currency,
            event_id_override=event_id,
        ):
            request_count += 1

        pending = state.pending
        if decision.carry_reversal:
            pending = _pending_from_decision(
                event_id=event_id,
                decision=decision,
                previous=previous,
                current=current,
            )
        state = replace(state, state=decision.desired_state, pending=pending)
        _persist_state_v2(state)

    # The second half of a carried flip is emitted only after Saxo is observed FLAT.
    # LIVE OPEN then independently requires settled close/P&L provenance, Product
    # Admission, current sizing/Margin Envelope and final Saxo precheck before POST.
    if state.pending is not None and observed_direction == DIRECTION_FLAT:
        pending = state.pending
        decision = _pending_decision(pending)
        synthetic_previous = MtfObservationV2(
            bar_time=pending.signal_at - timedelta(minutes=REGIME_TIMEFRAME_MINUTES),
            closed_at=pending.signal_at - timedelta(minutes=REGIME_TIMEFRAME_MINUTES),
            timeframe_minutes=REGIME_TIMEFRAME_MINUTES,
            close=float(by_tf[REGIME_TIMEFRAME_MINUTES][-1].close),
            macd=pending.previous_macd,
            signal=pending.previous_signal,
        )
        synthetic_current = MtfObservationV2(
            bar_time=pending.signal_at - timedelta(minutes=REGIME_TIMEFRAME_MINUTES),
            closed_at=pending.signal_at,
            timeframe_minutes=REGIME_TIMEFRAME_MINUTES,
            close=float(by_tf[REGIME_TIMEFRAME_MINUTES][-1].close),
            macd=pending.current_macd,
            signal=pending.current_signal,
        )
        latest_30m = _latest_at(by_tf[REGIME_TIMEFRAME_MINUTES], end)
        previous_30m, context_30m = _latest_pair_at(by_tf[REGIME_TIMEFRAME_MINUTES], end)
        long_context = regime_context_30m_v2(previous_30m, context_30m)
        short_context = short_regime_context_30m_v2(previous_30m, context_30m)
        if _persist_event_and_request_v2(
            enrollment=enrollment,
            state_before=state,
            decision=decision,
            previous=synthetic_previous,
            current=synthetic_current,
            long_context_30m=long_context,
            short_context_30m=short_context,
            latest_5m=_latest_at(by_tf[ENTRY_TIMEFRAME_MINUTES], end),
            latest_10m=_latest_at(by_tf[VALIDATION_TIMEFRAME_MINUTES], end),
            latest_30m=latest_30m,
            observed=observed,
            budget_amount=equity.entry_budget,
            budget_currency=equity.currency,
            event_id_override=pending.event_id,
        ):
            request_count += 1

    return MtfFlipLiveCycleV2(
        pilot_key=enrollment.pilot_key,
        state=state.state,
        pending_target=None if state.pending is None else state.pending.target_direction,
        processed=processed,
        events=event_count,
        requests=request_count,
        bootstrap=False,
    )


__all__ = [
    "MtfFlipLiveCycleV2",
    "MtfFlipLiveStateV2",
    "MtfFlipPendingV2",
    "ensure_mtf_flip_live_schema_v2",
    "load_mtf_flip_live_state_v2",
    "run_mtf_flip_live_strategy_once_v2",
]
