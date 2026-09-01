from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
import logging
import time
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from autotrader_cadence_v2 import sleep_to_fixed_start_cadence_v2
from autotrader_macd_dry_run_v2 import (
    SIGNAL_DOWN,
    SIGNAL_UP,
    MacdObservationV2,
    closed_30m_bars_v2,
    macd_observations_v2,
)
from autotrader_macd_flip_policy_v2 import MACD_FLIP_STRATEGY_V2
from autotrader_pilot_equity_v2 import load_pilot_equity_v2
from autotrader_position_controller_v2 import (
    ACTION_CLOSE,
    ACTION_HOLD,
    ACTION_OPEN,
    DIRECTION_FLAT,
    DIRECTION_LONG,
    DIRECTION_SHORT,
    PositionDecisionV2,
    PositionStateV2,
    PositionTargetV2,
    decide_position_action_v2,
)
from autotrader_risk_control_v2 import PositionObservationV2, _position_observations_v2
from autotrader_schema_v2 import ensure_autotrader_schema_v2
from autotrader_strategy_catalog_v2 import MACD_SHORT_FLAT_STRATEGY_V2, MTF_LONG_FLAT_STRATEGY_V2
from autotrader_strategy_enrollment_v2 import (
    EXECUTION_MODE_LIVE,
    StrategyEnrollmentV2,
    load_active_strategy_enrollments_v2,
)
from canonical_market_bars_v2 import CanonicalMarketBarStoreV2
from database import connect, using_postgres
from saxo_provider import configured_client


LOGGER = logging.getLogger("pricegauger.autotrader.automanage_runtime_v2")
MACD_LONG_FLAT_STRATEGY_V2 = "macd-30m-long-flat-v1"
AUTOMANAGE_RECIPE_V2 = "automanage-closed-30m-macd-v2.1"
SUPPORTED_STRATEGIES = {
    MACD_LONG_FLAT_STRATEGY_V2,
    MACD_SHORT_FLAT_STRATEGY_V2,
    MACD_FLIP_STRATEGY_V2,
}
REQUEST_PENDING = "PENDING"
REQUEST_SUPERSEDED = "SUPERSEDED"


@dataclass(frozen=True, slots=True)
class AutoManageIntentV2:
    event_id: str
    pilot_key: str
    strategy_key: str
    market_id: int
    market_name: str
    signal_at: datetime
    signal: str
    target_direction: str
    previous_macd: float
    previous_signal: float
    current_macd: float
    current_signal: float
    budget_amount: float
    budget_currency: str

    def __post_init__(self) -> None:
        if self.strategy_key not in SUPPORTED_STRATEGIES:
            raise ValueError(f"unsupported AutoManage strategy: {self.strategy_key}")
        if self.signal_at.tzinfo is None:
            raise ValueError("signal_at must be timezone-aware")
        if self.signal not in {SIGNAL_UP, SIGNAL_DOWN}:
            raise ValueError("unsupported MACD signal")
        if self.target_direction not in {DIRECTION_FLAT, DIRECTION_LONG, DIRECTION_SHORT}:
            raise ValueError("unsupported target direction")
        if float(self.budget_amount) < 0:
            raise ValueError("budget_amount cannot be negative")
        if not self.budget_currency.strip():
            raise ValueError("budget_currency is required")

    def to_position_target(self) -> PositionTargetV2:
        # PositionTarget requires a positive bookkeeping budget even for a FLAT
        # target. The execution request still carries the real (possibly zero)
        # settled pilot budget, and OPEN is blocked when that budget is exhausted.
        controller_budget = max(float(self.budget_amount), 1e-12)
        fraction = 0.0 if self.target_direction == DIRECTION_FLAT else 1.0
        return PositionTargetV2(
            market_id=int(self.market_id),
            market_name=self.market_name,
            direction=self.target_direction,
            target_fraction=fraction,
            budget_amount=controller_budget,
            budget_currency=self.budget_currency,
            strategy_key=self.strategy_key,
            signal_at=self.signal_at,
            rationale=(
                f"confirmed closed 30m MACD 12/26/9 {self.signal}; "
                f"{self.strategy_key} targets {self.target_direction}"
            ),
            source_fingerprint=self.event_id,
        )


@dataclass(frozen=True, slots=True)
class AutoManageRuntimeStateV2:
    last_evaluated_bar_time: datetime | None = None
    pending_intent: AutoManageIntentV2 | None = None


@dataclass(frozen=True, slots=True)
class AutoManageEvaluationV2:
    evaluation_id: str
    enrollment: StrategyEnrollmentV2
    latest_closed_bar_time: datetime
    observed_position: PositionObservationV2 | None
    observed_state: PositionStateV2
    outcome_reason: str
    intent: AutoManageIntentV2 | None
    decision: PositionDecisionV2 | None
    next_state: AutoManageRuntimeStateV2


def _utc(value: Any) -> datetime | None:
    if value is None:
        return None
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _row_value(row: Any, key: str, index: int) -> Any:
    if isinstance(row, dict):
        return row[key]
    try:
        return row[key]
    except (TypeError, IndexError):
        return row[index]


def _cross(previous: MacdObservationV2, current: MacdObservationV2) -> str | None:
    if previous.spread <= 0.0 < current.spread:
        return SIGNAL_UP
    if previous.spread >= 0.0 > current.spread:
        return SIGNAL_DOWN
    return None


def _target_direction(strategy_key: str, signal: str) -> str:
    if strategy_key == MACD_LONG_FLAT_STRATEGY_V2:
        if signal == SIGNAL_UP:
            return DIRECTION_LONG
        if signal == SIGNAL_DOWN:
            return DIRECTION_FLAT
    if strategy_key == MACD_SHORT_FLAT_STRATEGY_V2:
        if signal == SIGNAL_UP:
            return DIRECTION_FLAT
        if signal == SIGNAL_DOWN:
            return DIRECTION_SHORT
    if strategy_key == MACD_FLIP_STRATEGY_V2:
        if signal == SIGNAL_UP:
            return DIRECTION_LONG
        if signal == SIGNAL_DOWN:
            return DIRECTION_SHORT
    raise ValueError(f"unsupported strategy/signal combination: {strategy_key}/{signal}")


def _intent_from_pair(
    *,
    enrollment: StrategyEnrollmentV2,
    previous: MacdObservationV2,
    current: MacdObservationV2,
    budget_amount: float,
    budget_currency: str,
) -> AutoManageIntentV2 | None:
    signal = _cross(previous, current)
    if signal is None:
        return None
    target = _target_direction(enrollment.strategy_key, signal)
    identity = "|".join(
        (
            enrollment.strategy_key,
            enrollment.pilot_key,
            current.bar_time.isoformat(),
            signal,
            target,
        )
    )
    return AutoManageIntentV2(
        event_id=str(uuid5(NAMESPACE_URL, identity)),
        pilot_key=enrollment.pilot_key,
        strategy_key=enrollment.strategy_key,
        market_id=enrollment.market_id,
        market_name=enrollment.market_name,
        signal_at=current.bar_time,
        signal=signal,
        target_direction=target,
        previous_macd=previous.macd,
        previous_signal=previous.signal,
        current_macd=current.macd,
        current_signal=current.signal,
        budget_amount=max(0.0, float(budget_amount)),
        budget_currency=budget_currency,
    )


def _position_state(observation: PositionObservationV2 | None) -> PositionStateV2:
    if observation is None:
        return PositionStateV2(direction=DIRECTION_FLAT, deployed_fraction=0.0)
    side = observation.direction.strip().lower()
    if side == "buy":
        direction = DIRECTION_LONG
    elif side == "sell":
        direction = DIRECTION_SHORT
    else:
        raise ValueError(f"unsupported Saxo position direction: {observation.direction}")
    return PositionStateV2(direction=direction, deployed_fraction=1.0)


def _plan_intent(current: PositionStateV2, intent: AutoManageIntentV2) -> PositionDecisionV2:
    target = intent.to_position_target()
    # Pilot policy: no same-side pyramiding/rebalancing. Existing desired exposure
    # is treated as the full target even if its market value has drifted.
    if current.direction == intent.target_direction and current.deployed_fraction > 1e-12:
        target = replace(target, target_fraction=float(current.deployed_fraction))
    return decide_position_action_v2(current, target)


def plan_automanage_step_v2(
    *,
    enrollment: StrategyEnrollmentV2,
    state: AutoManageRuntimeStateV2,
    observed_position: PositionObservationV2 | None,
    previous: MacdObservationV2,
    current: MacdObservationV2,
    budget_amount: float,
    budget_currency: str,
) -> AutoManageEvaluationV2:
    if enrollment.strategy_key not in SUPPORTED_STRATEGIES:
        raise ValueError("unsupported strategy enrollment")
    if previous.bar_time >= current.bar_time:
        raise ValueError("MACD observation pair must be strictly ordered")

    observed_state = _position_state(observed_position)
    prior_bar = state.last_evaluated_bar_time
    pending = state.pending_intent
    intent: AutoManageIntentV2 | None = None
    decision: PositionDecisionV2 | None = None
    outcome = "NO_NEW_CROSS"

    if prior_bar is None:
        # Enrollment adopts the actual current exposure. Historical MACD regime is
        # never replayed into a live order on bootstrap.
        pending = None
        outcome = "BOOTSTRAP_NO_REPLAY"
    else:
        fresh = None
        if current.bar_time > prior_bar:
            fresh = _intent_from_pair(
                enrollment=enrollment,
                previous=previous,
                current=current,
                budget_amount=budget_amount,
                budget_currency=budget_currency,
            )
        if fresh is not None:
            intent = fresh
            decision = _plan_intent(observed_state, intent)
            outcome = "FRESH_MACD_CROSS"
            # Only a strategy-origin direction reversal may carry an old signal
            # across CLOSE -> confirmed FLAT -> OPEN. A target-FLAT close never
            # creates a re-entry intent.
            if (
                decision.action == ACTION_CLOSE
                and decision.desired_direction in {DIRECTION_LONG, DIRECTION_SHORT}
                and decision.desired_direction != decision.prior_direction
            ):
                pending = intent
            else:
                pending = None
        elif pending is not None:
            # Refresh capital before the eventual opposite OPEN so realized P/L from
            # the just-closed leg can compound without changing signal identity.
            pending = replace(
                pending,
                budget_amount=max(0.0, float(budget_amount)),
                budget_currency=budget_currency,
            )
            intent = pending
            decision = _plan_intent(observed_state, intent)
            if observed_state.direction == pending.target_direction and observed_state.deployed_fraction > 1e-12:
                pending = None
                outcome = "REVERSAL_TARGET_OBSERVED"
            elif decision.action == ACTION_OPEN and float(budget_amount) <= 0:
                outcome = "ENTRY_BLOCKED_EQUITY_EXHAUSTED"
            else:
                outcome = "REVERSAL_PENDING"

    if decision is not None and decision.action == ACTION_OPEN and float(budget_amount) <= 0:
        outcome = "ENTRY_BLOCKED_EQUITY_EXHAUSTED"

    latest = current.bar_time if prior_bar is None or current.bar_time > prior_bar else prior_bar
    next_state = AutoManageRuntimeStateV2(last_evaluated_bar_time=latest, pending_intent=pending)
    identity = "|".join(
        (
            AUTOMANAGE_RECIPE_V2,
            enrollment.pilot_key,
            current.bar_time.isoformat(),
            "FLAT" if observed_position is None else observed_position.net_position_id,
            observed_state.direction,
            "NO_INTENT" if intent is None else intent.event_id,
            "NO_ACTION" if decision is None else decision.action,
            outcome,
        )
    )
    return AutoManageEvaluationV2(
        evaluation_id=str(uuid5(NAMESPACE_URL, identity)),
        enrollment=enrollment,
        latest_closed_bar_time=current.bar_time,
        observed_position=observed_position,
        observed_state=observed_state,
        outcome_reason=outcome,
        intent=intent,
        decision=decision,
        next_state=next_state,
    )


def load_automanage_runtime_state_v2(enrollment: StrategyEnrollmentV2) -> AutoManageRuntimeStateV2:
    ensure_autotrader_schema_v2()
    with connect() as db:
        row = db.execute(
            """
            SELECT strategy_key, last_evaluated_bar_time,
                   pending_intent_id, pending_signal_at, pending_signal,
                   pending_target_direction, pending_previous_macd,
                   pending_previous_signal, pending_current_macd,
                   pending_current_signal, pending_budget_amount,
                   pending_budget_currency
            FROM pg_v2_autotrader_strategy_runtime_state
            WHERE pilot_key = ?
            """,
            (enrollment.pilot_key,),
        ).fetchone()
    if row is None:
        return AutoManageRuntimeStateV2()
    if str(_row_value(row, "strategy_key", 0)) != enrollment.strategy_key:
        raise ValueError("persisted strategy runtime state has mismatched strategy_key")
    pending_id = _row_value(row, "pending_intent_id", 2)
    pending = None
    if pending_id is not None:
        signal_at = _utc(_row_value(row, "pending_signal_at", 3))
        if signal_at is None:
            raise ValueError("pending intent missing signal_at")
        pending = AutoManageIntentV2(
            event_id=str(pending_id),
            pilot_key=enrollment.pilot_key,
            strategy_key=enrollment.strategy_key,
            market_id=enrollment.market_id,
            market_name=enrollment.market_name,
            signal_at=signal_at,
            signal=str(_row_value(row, "pending_signal", 4)),
            target_direction=str(_row_value(row, "pending_target_direction", 5)),
            previous_macd=float(_row_value(row, "pending_previous_macd", 6)),
            previous_signal=float(_row_value(row, "pending_previous_signal", 7)),
            current_macd=float(_row_value(row, "pending_current_macd", 8)),
            current_signal=float(_row_value(row, "pending_current_signal", 9)),
            budget_amount=float(_row_value(row, "pending_budget_amount", 10)),
            budget_currency=str(_row_value(row, "pending_budget_currency", 11)),
        )
    return AutoManageRuntimeStateV2(
        last_evaluated_bar_time=_utc(_row_value(row, "last_evaluated_bar_time", 1)),
        pending_intent=pending,
    )


def _persist_evaluation_and_request(evaluation: AutoManageEvaluationV2) -> None:
    enrollment = evaluation.enrollment
    state = evaluation.next_state
    pending = state.pending_intent
    intent = evaluation.intent
    decision = evaluation.decision
    observed = evaluation.observed_position
    request_id: str | None = None
    request_action: str | None = None
    if (
        intent is not None
        and decision is not None
        and decision.action in {ACTION_CLOSE, ACTION_OPEN}
        and not (decision.action == ACTION_OPEN and intent.budget_amount <= 0)
    ):
        request_action = decision.action
        request_id = str(
            uuid5(
                NAMESPACE_URL,
                f"automanage-execution|{evaluation.evaluation_id}|{decision.action}|{decision.desired_direction}",
            )
        )

    with connect() as db:
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
                evaluation.evaluation_id,
                enrollment.pilot_key,
                enrollment.strategy_key,
                evaluation.latest_closed_bar_time,
                None if observed is None else observed.net_position_id,
                evaluation.observed_state.direction,
                evaluation.outcome_reason,
                None if intent is None else intent.event_id,
                None if intent is None else intent.signal_at,
                None if intent is None else intent.signal,
                None if intent is None else intent.target_direction,
                None if intent is None else intent.previous_macd,
                None if intent is None else intent.previous_signal,
                None if intent is None else intent.current_macd,
                None if intent is None else intent.current_signal,
                None if decision is None else decision.action,
                None if decision is None else decision.desired_direction,
                None if intent is None else intent.budget_amount,
                None if intent is None else intent.budget_currency,
                request_id,
            ),
        )
        if request_id is not None and request_action is not None and intent is not None:
            # A newer strategy signal supersedes only requests that have not started
            # execution. SUBMITTING/accepted/uncertain requests are never rewritten.
            db.execute(
                """
                UPDATE pg_v2_autotrader_execution_requests
                SET status = ?, block_reason = 'NEWER_STRATEGY_SIGNAL', updated_at = now()
                WHERE pilot_key = ? AND status = ? AND request_id <> ?
                """,
                (REQUEST_SUPERSEDED, enrollment.pilot_key, REQUEST_PENDING, request_id),
            )
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
                    evaluation.evaluation_id,
                    enrollment.pilot_key,
                    enrollment.strategy_key,
                    request_action,
                    decision.desired_direction,
                    intent.signal_at,
                    intent.signal,
                    enrollment.account_id,
                    None if observed is None else observed.net_position_id,
                    evaluation.observed_state.direction,
                    None if observed is None else observed.amount,
                    None if observed is None else observed.average_open_price,
                    enrollment.uic,
                    enrollment.asset_type,
                    enrollment.market_id,
                    enrollment.instrument_id,
                    intent.budget_amount,
                    intent.budget_currency,
                    REQUEST_PENDING,
                ),
            )

        db.execute(
            """
            INSERT INTO pg_v2_autotrader_strategy_runtime_state(
                pilot_key, strategy_key, last_evaluated_bar_time,
                pending_intent_id, pending_signal_at, pending_signal,
                pending_target_direction, pending_previous_macd,
                pending_previous_signal, pending_current_macd,
                pending_current_signal, pending_budget_amount,
                pending_budget_currency, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, now())
            ON CONFLICT (pilot_key) DO UPDATE SET
                strategy_key=EXCLUDED.strategy_key,
                last_evaluated_bar_time=EXCLUDED.last_evaluated_bar_time,
                pending_intent_id=EXCLUDED.pending_intent_id,
                pending_signal_at=EXCLUDED.pending_signal_at,
                pending_signal=EXCLUDED.pending_signal,
                pending_target_direction=EXCLUDED.pending_target_direction,
                pending_previous_macd=EXCLUDED.pending_previous_macd,
                pending_previous_signal=EXCLUDED.pending_previous_signal,
                pending_current_macd=EXCLUDED.pending_current_macd,
                pending_current_signal=EXCLUDED.pending_current_signal,
                pending_budget_amount=EXCLUDED.pending_budget_amount,
                pending_budget_currency=EXCLUDED.pending_budget_currency,
                updated_at=now()
            """,
            (
                enrollment.pilot_key,
                enrollment.strategy_key,
                state.last_evaluated_bar_time,
                None if pending is None else pending.event_id,
                None if pending is None else pending.signal_at,
                None if pending is None else pending.signal,
                None if pending is None else pending.target_direction,
                None if pending is None else pending.previous_macd,
                None if pending is None else pending.previous_signal,
                None if pending is None else pending.current_macd,
                None if pending is None else pending.current_signal,
                None if pending is None else pending.budget_amount,
                None if pending is None else pending.budget_currency,
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
        raise RuntimeError("multiple live Saxo net positions match one AutoManage product")
    return matches[0] if matches else None


def run_automanage_strategy_once_v2(
    enrollment: StrategyEnrollmentV2,
    *,
    db_path: str = "pricegauger.db",
    now: datetime | None = None,
    observations: tuple[PositionObservationV2, ...] | None = None,
) -> AutoManageEvaluationV2:
    if enrollment.execution_mode != EXECUTION_MODE_LIVE or not enrollment.enabled:
        raise ValueError("strategy runtime only executes active LIVE_MANAGE enrollments")
    ensure_autotrader_schema_v2()
    if enrollment.strategy_key not in SUPPORTED_STRATEGIES:
        raise ValueError("unsupported strategy")

    end = now or datetime.now(timezone.utc)
    if end.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    end = end.astimezone(timezone.utc)
    start = end - timedelta(days=14)
    bars = CanonicalMarketBarStoreV2(db_path).load_instrument_range(
        instrument_id=enrollment.instrument_id,
        start=start,
        end=end,
        limit=50000,
    )
    points = tuple(item.point for item in bars)
    if not points:
        raise ValueError("AutoManage has no exact canonical 1m history")
    closed = closed_30m_bars_v2(points, market=enrollment.market_name)
    macd = macd_observations_v2(closed)
    if len(macd) < 2:
        raise ValueError("AutoManage needs enough closed 30m bars for MACD 12/26/9")

    if observations is None:
        client = configured_client()
        if client is None:
            raise RuntimeError("Saxo client is not configured")
        observations = _position_observations_v2(client)
    observed = _exact_product_observation(enrollment, observations)
    state = load_automanage_runtime_state_v2(enrollment)
    equity = load_pilot_equity_v2(pilot_key=enrollment.pilot_key)
    evaluation = plan_automanage_step_v2(
        enrollment=enrollment,
        state=state,
        observed_position=observed,
        previous=macd[-2],
        current=macd[-1],
        budget_amount=equity.entry_budget,
        budget_currency=equity.currency,
    )
    _persist_evaluation_and_request(evaluation)
    return evaluation


def run_automanage_strategy_cycle_v2(*, db_path: str = "pricegauger.db") -> tuple[int, int]:
    if not using_postgres():
        return (0, 0)
    enrollments = tuple(
        item
        for item in load_active_strategy_enrollments_v2()
        if item.execution_mode == EXECUTION_MODE_LIVE and item.enabled
    )
    if not enrollments:
        return (0, 0)
    client = configured_client()
    if client is None:
        raise RuntimeError("Saxo client is not configured")
    observations = _position_observations_v2(client)
    evaluated = 0
    failed = 0
    for enrollment in enrollments:
        try:
            if enrollment.strategy_key == MTF_LONG_FLAT_STRATEGY_V2:
                from autotrader_mtf_live_runtime_v2 import run_mtf_live_strategy_once_v2

                run_mtf_live_strategy_once_v2(
                    enrollment,
                    db_path=db_path,
                    observations=observations,
                )
            else:
                run_automanage_strategy_once_v2(
                    enrollment,
                    db_path=db_path,
                    observations=observations,
                )
            evaluated += 1
        except Exception as exc:
            failed += 1
            LOGGER.warning(
                "AutoManage strategy evaluation failed pilot=%s: %s",
                enrollment.pilot_key,
                exc,
                exc_info=True,
            )
    return evaluated, failed


def run_automanage_strategy_forever_v2(
    *,
    db_path: str = "pricegauger.db",
    interval_seconds: int = 15,
) -> None:
    interval = max(5, int(interval_seconds))
    while True:
        started = time.monotonic()
        try:
            run_automanage_strategy_cycle_v2(db_path=db_path)
        except Exception as exc:
            LOGGER.warning("AutoManage strategy cycle failed: %s", exc, exc_info=True)
        sleep_to_fixed_start_cadence_v2(started, interval)


__all__ = [
    "AUTOMANAGE_RECIPE_V2",
    "AutoManageEvaluationV2",
    "AutoManageIntentV2",
    "AutoManageRuntimeStateV2",
    "MACD_LONG_FLAT_STRATEGY_V2",
    "MACD_SHORT_FLAT_STRATEGY_V2",
    "REQUEST_PENDING",
    "REQUEST_SUPERSEDED",
    "load_automanage_runtime_state_v2",
    "plan_automanage_step_v2",
    "run_automanage_strategy_cycle_v2",
    "run_automanage_strategy_forever_v2",
    "run_automanage_strategy_once_v2",
]
