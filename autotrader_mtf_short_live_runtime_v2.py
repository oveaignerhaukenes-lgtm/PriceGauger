from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from autotrader_mtf_entry_shadow_v2 import (
    ACTION_CONFIRMATION,
    ACTION_WOULD_EXIT,
    ACTION_WOULD_EXIT_REARM,
    ENTRY_TIMEFRAME_MINUTES,
    MtfDecisionV2,
    MtfObservationV2,
    REGIME_TIMEFRAME_MINUTES,
    VALIDATION_TIMEFRAME_MINUTES,
    closed_bars_v2,
    macd_observations_v2,
)
from autotrader_mtf_short_policy_v2 import (
    ACTION_WOULD_SELL,
    EVENT_ENTRY_5M_SHORT,
    STATE_CONFIRMED_30M_SHORT,
    STATE_FLAT,
    STATE_PROVISIONAL_SHORT,
    short_decision_for_observation_v2,
    short_regime_context_30m_v2,
)
from autotrader_pilot_equity_v2 import load_pilot_equity_v2
from autotrader_risk_control_v2 import PositionObservationV2, _position_observations_v2
from autotrader_schema_v2 import ensure_autotrader_schema_v2
from autotrader_strategy_catalog_v2 import MTF_SHORT_FLAT_STRATEGY_V2
from autotrader_strategy_enrollment_v2 import EXECUTION_MODE_LIVE, StrategyEnrollmentV2
from canonical_market_bars_v2 import CanonicalMarketBarStoreV2
from database import connect
from saxo_provider import configured_client


REQUEST_PENDING = "PENDING"
REQUEST_APPROVED = "APPROVED"
REQUEST_SUPERSEDED = "SUPERSEDED"
_TIMEFRAMES = (ENTRY_TIMEFRAME_MINUTES, VALIDATION_TIMEFRAME_MINUTES, REGIME_TIMEFRAME_MINUTES)
_PRIORITY = {REGIME_TIMEFRAME_MINUTES: 0, ENTRY_TIMEFRAME_MINUTES: 1, VALIDATION_TIMEFRAME_MINUTES: 2}


@dataclass(frozen=True, slots=True)
class MtfShortLiveStateV2:
    pilot_key: str
    state: str
    last_5m_closed_at: datetime | None = None
    last_10m_closed_at: datetime | None = None
    last_30m_closed_at: datetime | None = None
    entry_at: datetime | None = None
    entry_price: float | None = None


@dataclass(frozen=True, slots=True)
class MtfShortLiveCycleV2:
    pilot_key: str
    state: str
    processed: int
    events: int
    requests: int
    bootstrap: bool


def _utc(value: Any) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def ensure_mtf_short_live_schema_v2() -> None:
    ensure_autotrader_schema_v2()
    with connect() as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS pg_v2_autotrader_mtf_short_live_state (
                pilot_key TEXT PRIMARY KEY REFERENCES pg_v2_autotrader_strategy_enrollments(pilot_key),
                strategy_key TEXT NOT NULL,
                state TEXT NOT NULL CHECK (state IN ('FLAT','PROVISIONAL_SHORT','VALIDATED_10M_SHORT','CONFIRMED_30M_SHORT')),
                last_5m_closed_at TIMESTAMPTZ,
                last_10m_closed_at TIMESTAMPTZ,
                last_30m_closed_at TIMESTAMPTZ,
                entry_at TIMESTAMPTZ,
                entry_price DOUBLE PRECISION,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS pg_v2_autotrader_mtf_short_live_events (
                event_id UUID PRIMARY KEY,
                pilot_key TEXT NOT NULL REFERENCES pg_v2_autotrader_strategy_enrollments(pilot_key),
                event_type TEXT NOT NULL,
                action TEXT NOT NULL,
                action_at TIMESTAMPTZ NOT NULL,
                price DOUBLE PRECISION NOT NULL,
                prior_state TEXT NOT NULL,
                desired_state TEXT NOT NULL,
                reason TEXT NOT NULL,
                context_30m TEXT NOT NULL,
                spread_5m DOUBLE PRECISION,
                spread_10m DOUBLE PRECISION,
                spread_30m DOUBLE PRECISION,
                execution_request_id UUID,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE(pilot_key, event_type, action_at)
            )
            """
        )


def _row_dict(row: Any) -> dict[str, Any]:
    return dict(row) if not isinstance(row, dict) else row


def load_mtf_short_live_state_v2(pilot_key: str) -> MtfShortLiveStateV2 | None:
    ensure_mtf_short_live_schema_v2()
    with connect() as db:
        row = db.execute(
            """
            SELECT state, last_5m_closed_at, last_10m_closed_at, last_30m_closed_at,
                   entry_at, entry_price
            FROM pg_v2_autotrader_mtf_short_live_state
            WHERE pilot_key = ? AND strategy_key = ?
            """,
            (str(pilot_key), MTF_SHORT_FLAT_STRATEGY_V2),
        ).fetchone()
    if row is None:
        return None
    item = _row_dict(row)
    return MtfShortLiveStateV2(
        pilot_key=str(pilot_key),
        state=str(item["state"]),
        last_5m_closed_at=None if item["last_5m_closed_at"] is None else _utc(item["last_5m_closed_at"]),
        last_10m_closed_at=None if item["last_10m_closed_at"] is None else _utc(item["last_10m_closed_at"]),
        last_30m_closed_at=None if item["last_30m_closed_at"] is None else _utc(item["last_30m_closed_at"]),
        entry_at=None if item["entry_at"] is None else _utc(item["entry_at"]),
        entry_price=None if item["entry_price"] is None else float(item["entry_price"]),
    )


def _persist_state_v2(state: MtfShortLiveStateV2) -> None:
    with connect() as db:
        db.execute(
            """
            INSERT INTO pg_v2_autotrader_mtf_short_live_state(
                pilot_key, strategy_key, state, last_5m_closed_at, last_10m_closed_at,
                last_30m_closed_at, entry_at, entry_price, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, now())
            ON CONFLICT (pilot_key) DO UPDATE SET
                strategy_key=EXCLUDED.strategy_key,
                state=EXCLUDED.state,
                last_5m_closed_at=EXCLUDED.last_5m_closed_at,
                last_10m_closed_at=EXCLUDED.last_10m_closed_at,
                last_30m_closed_at=EXCLUDED.last_30m_closed_at,
                entry_at=EXCLUDED.entry_at,
                entry_price=EXCLUDED.entry_price,
                updated_at=now()
            """,
            (
                state.pilot_key,
                MTF_SHORT_FLAT_STRATEGY_V2,
                state.state,
                state.last_5m_closed_at,
                state.last_10m_closed_at,
                state.last_30m_closed_at,
                state.entry_at,
                state.entry_price,
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
        raise RuntimeError("multiple Saxo positions match one MTF SHORT LIVE product")
    return matches[0] if matches else None


def _observed_direction(observation: PositionObservationV2 | None) -> str:
    if observation is None:
        return "FLAT"
    side = observation.direction.strip().lower()
    if side == "buy":
        return "LONG"
    if side == "sell":
        return "SHORT"
    raise ValueError(f"unsupported Saxo position direction: {observation.direction}")


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


def _cursor(state: MtfShortLiveStateV2, timeframe: int) -> datetime | None:
    return {
        ENTRY_TIMEFRAME_MINUTES: state.last_5m_closed_at,
        VALIDATION_TIMEFRAME_MINUTES: state.last_10m_closed_at,
        REGIME_TIMEFRAME_MINUTES: state.last_30m_closed_at,
    }[int(timeframe)]


def _advance_state(
    state: MtfShortLiveStateV2,
    *,
    observation: MtfObservationV2,
    decision: MtfDecisionV2 | None,
) -> MtfShortLiveStateV2:
    updates = {
        ENTRY_TIMEFRAME_MINUTES: {"last_5m_closed_at": observation.closed_at},
        VALIDATION_TIMEFRAME_MINUTES: {"last_10m_closed_at": observation.closed_at},
        REGIME_TIMEFRAME_MINUTES: {"last_30m_closed_at": observation.closed_at},
    }[observation.timeframe_minutes]
    next_state = state.state if decision is None else decision.desired_state
    entry_at = state.entry_at
    entry_price = state.entry_price
    if decision is not None and decision.event_type == EVENT_ENTRY_5M_SHORT:
        entry_at = observation.closed_at
        entry_price = float(observation.close)
    elif decision is not None and decision.desired_state == STATE_FLAT:
        entry_at = None
        entry_price = None
    return replace(state, state=next_state, entry_at=entry_at, entry_price=entry_price, **updates)


def _latest_work(
    state: MtfShortLiveStateV2,
    observations: dict[int, tuple[MtfObservationV2, ...]],
    *,
    now: datetime,
) -> tuple[tuple[int, MtfObservationV2, MtfObservationV2, bool], ...]:
    """Process only the latest current pair per timeframe; never replay backlog."""
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


def _target_direction(decision: MtfDecisionV2) -> str | None:
    if decision.action == ACTION_WOULD_SELL:
        return "SHORT"
    if decision.action in {ACTION_WOULD_EXIT, ACTION_WOULD_EXIT_REARM}:
        return "FLAT"
    if decision.action == ACTION_CONFIRMATION:
        return None
    raise ValueError(f"unsupported MTF SHORT action: {decision.action}")


def _request_action(observed_direction: str, desired_direction: str | None) -> str | None:
    if desired_direction is None:
        return None
    if observed_direction == "LONG":
        raise ValueError("MTF short/flat cannot manage an observed LONG exposure")
    if desired_direction == "SHORT":
        return "OPEN" if observed_direction == "FLAT" else None
    if desired_direction == "FLAT":
        return "CLOSE" if observed_direction == "SHORT" else None
    raise ValueError(f"unsupported MTF SHORT desired direction: {desired_direction}")


def _persist_event_and_request_v2(
    *,
    enrollment: StrategyEnrollmentV2,
    state_before: MtfShortLiveStateV2,
    decision: MtfDecisionV2,
    previous: MtfObservationV2,
    current: MtfObservationV2,
    context_30m: str,
    latest_5m: MtfObservationV2 | None,
    latest_10m: MtfObservationV2 | None,
    latest_30m: MtfObservationV2 | None,
    observed: PositionObservationV2 | None,
    budget_amount: float,
    budget_currency: str,
) -> bool:
    observed_direction = _observed_direction(observed)
    desired_direction = _target_direction(decision)
    request_action = _request_action(observed_direction, desired_direction)
    if request_action == "OPEN" and float(budget_amount) <= 0:
        request_action = None
        outcome = "MTF_SHORT_ENTRY_BLOCKED_EQUITY_EXHAUSTED"
    elif desired_direction is None:
        outcome = f"MTF_SHORT_{decision.event_type}"
    elif request_action is None:
        outcome = "MTF_SHORT_TARGET_ALREADY_OBSERVED"
    else:
        outcome = f"MTF_SHORT_{decision.event_type}_REQUESTED"

    signal = None
    if decision.action == ACTION_WOULD_SELL:
        signal = "CROSS_DOWN"
    elif decision.action in {ACTION_WOULD_EXIT, ACTION_WOULD_EXIT_REARM}:
        signal = "CROSS_UP"

    event_id = str(
        uuid5(
            NAMESPACE_URL,
            f"mtf-short-live-event|{enrollment.pilot_key}|{decision.event_type}|{current.closed_at.isoformat()}",
        )
    )
    evaluation_id = str(uuid5(NAMESPACE_URL, f"mtf-short-live-evaluation|{event_id}"))
    request_id = None
    if request_action is not None and signal is not None:
        request_id = str(
            uuid5(
                NAMESPACE_URL,
                f"mtf-short-live-execution|{event_id}|{request_action}|{desired_direction}",
            )
        )

    with connect() as db:
        if signal is not None:
            db.execute(
                """
                UPDATE pg_v2_autotrader_execution_requests
                SET status = ?, block_reason = 'NEWER_MTF_SHORT_SIGNAL', updated_at = now()
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

        if request_id is not None and request_action is not None and signal is not None:
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
            INSERT INTO pg_v2_autotrader_mtf_short_live_events(
                event_id, pilot_key, event_type, action, action_at, price,
                prior_state, desired_state, reason, context_30m,
                spread_5m, spread_10m, spread_30m, execution_request_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                decision.reason,
                context_30m,
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
) -> MtfShortLiveStateV2:
    direction = _observed_direction(observed)
    if direction == "LONG":
        raise ValueError("MTF short/flat cannot bootstrap from a LONG position")
    state_name = STATE_CONFIRMED_30M_SHORT if direction == "SHORT" else STATE_FLAT
    state = MtfShortLiveStateV2(
        pilot_key=enrollment.pilot_key,
        state=state_name,
        last_5m_closed_at=observations[ENTRY_TIMEFRAME_MINUTES][-1].closed_at,
        last_10m_closed_at=observations[VALIDATION_TIMEFRAME_MINUTES][-1].closed_at,
        last_30m_closed_at=observations[REGIME_TIMEFRAME_MINUTES][-1].closed_at,
    )
    _persist_state_v2(state)
    latest = max(item[-1].closed_at for item in observations.values())
    with connect() as db:
        evaluation_id = str(
            uuid5(NAMESPACE_URL, f"mtf-short-live-bootstrap|{enrollment.pilot_key}|{latest.isoformat()}")
        )
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


def run_mtf_short_live_strategy_once_v2(
    enrollment: StrategyEnrollmentV2,
    *,
    db_path: str = "pricegauger.db",
    now: datetime | None = None,
    observations: tuple[PositionObservationV2, ...] | None = None,
) -> MtfShortLiveCycleV2:
    if enrollment.execution_mode != EXECUTION_MODE_LIVE or not enrollment.enabled:
        raise ValueError("MTF SHORT runtime only executes active LIVE_MANAGE enrollments")
    if enrollment.strategy_key != MTF_SHORT_FLAT_STRATEGY_V2:
        raise ValueError("MTF SHORT runtime received a non-MTF-short strategy")
    ensure_mtf_short_live_schema_v2()

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
        raise ValueError("MTF SHORT LIVE has no exact canonical 1m history")

    by_tf: dict[int, tuple[MtfObservationV2, ...]] = {}
    for timeframe in _TIMEFRAMES:
        closed = closed_bars_v2(points, market=enrollment.market_name, timeframe_minutes=timeframe)
        items = macd_observations_v2(closed, timeframe_minutes=timeframe)
        if len(items) < 2:
            raise ValueError(f"MTF SHORT LIVE needs enough closed {timeframe}m bars for MACD 12/26/9")
        by_tf[timeframe] = items

    if observations is None:
        client = configured_client()
        if client is None:
            raise RuntimeError("Saxo client is not configured")
        observations = _position_observations_v2(client)
    observed = _exact_product_observation(enrollment, observations)

    state = load_mtf_short_live_state_v2(enrollment.pilot_key)
    if state is None:
        state = _bootstrap_state_v2(enrollment=enrollment, observed=observed, observations=by_tf)
        return MtfShortLiveCycleV2(enrollment.pilot_key, state.state, 0, 0, 0, True)

    equity = load_pilot_equity_v2(pilot_key=enrollment.pilot_key)
    processed = 0
    event_count = 0
    request_count = 0
    for timeframe, previous, current, fresh in _latest_work(state, by_tf, now=end):
        processed += 1
        if not fresh:
            state = _advance_state(state, observation=current, decision=None)
            _persist_state_v2(state)
            continue

        previous_30m, latest_30m = _latest_pair_at(by_tf[REGIME_TIMEFRAME_MINUTES], current.closed_at)
        context_30m = short_regime_context_30m_v2(previous_30m, latest_30m)
        latest_5m = _latest_at(by_tf[ENTRY_TIMEFRAME_MINUTES], current.closed_at)
        latest_10m = _latest_at(by_tf[VALIDATION_TIMEFRAME_MINUTES], current.closed_at)
        decision = short_decision_for_observation_v2(
            state=state.state,
            timeframe_minutes=timeframe,
            previous=previous,
            current=current,
            context_30m=context_30m,
        )
        prior_state = state
        if decision is not None:
            event_count += 1
            if _persist_event_and_request_v2(
                enrollment=enrollment,
                state_before=prior_state,
                decision=decision,
                previous=previous,
                current=current,
                context_30m=context_30m,
                latest_5m=latest_5m,
                latest_10m=latest_10m,
                latest_30m=latest_30m,
                observed=observed,
                budget_amount=equity.entry_budget,
                budget_currency=equity.currency,
            ):
                request_count += 1
        state = _advance_state(state, observation=current, decision=decision)
        _persist_state_v2(state)

    return MtfShortLiveCycleV2(
        pilot_key=enrollment.pilot_key,
        state=state.state,
        processed=processed,
        events=event_count,
        requests=request_count,
        bootstrap=False,
    )


__all__ = [
    "MtfShortLiveCycleV2",
    "MtfShortLiveStateV2",
    "ensure_mtf_short_live_schema_v2",
    "load_mtf_short_live_state_v2",
    "run_mtf_short_live_strategy_once_v2",
]
