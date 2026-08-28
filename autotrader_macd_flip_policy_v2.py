from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Iterable
from uuid import NAMESPACE_URL, uuid5

from autotrader_macd_dry_run_v2 import (
    SIGNAL_DOWN,
    SIGNAL_UP,
    MacdObservationV2,
    closed_30m_bars_v2,
    macd_observations_v2,
)
from autotrader_position_controller_v2 import (
    DIRECTION_FLAT,
    DIRECTION_LONG,
    DIRECTION_SHORT,
    PositionDecisionV2,
    PositionStateV2,
    PositionTargetV2,
    decide_position_action_v2,
)


MACD_FLIP_STRATEGY_V2 = "macd-30m-long-short-v1"
MACD_FLIP_RECIPE_V2 = "autotrader-macd-flip-v2.1"


@dataclass(frozen=True, slots=True)
class MacdFlipIntentV2:
    """One immutable closed-bar MACD direction-change intent.

    This object is strategy output, not an order. Execution is deliberately
    downstream. A persisted intent can be replayed across lifecycle cycles so a
    reversal remains CLOSE -> confirmed FLAT -> OPEN, never one reverse order.
    """

    event_id: str
    market_id: int
    market_name: str
    signal_at: datetime
    signal: str
    target_direction: str
    previous_macd: float
    previous_signal: float
    current_macd: float
    current_signal: float
    target_fraction: float
    budget_amount: float
    budget_currency: str = "NOK"
    strategy_key: str = MACD_FLIP_STRATEGY_V2

    def __post_init__(self) -> None:
        if self.signal_at.tzinfo is None:
            raise ValueError("signal_at must be timezone-aware")
        if self.signal not in {SIGNAL_UP, SIGNAL_DOWN}:
            raise ValueError(f"unsupported MACD signal: {self.signal}")
        expected = DIRECTION_LONG if self.signal == SIGNAL_UP else DIRECTION_SHORT
        if self.target_direction != expected:
            raise ValueError("target_direction must match MACD cross direction")
        if not 0.0 < float(self.target_fraction) <= 1.0:
            raise ValueError("target_fraction must be > 0 and <= 1")
        if float(self.budget_amount) <= 0:
            raise ValueError("budget_amount must be positive")
        if not str(self.budget_currency).strip():
            raise ValueError("budget_currency is required")

    @property
    def previous_spread(self) -> float:
        return float(self.previous_macd) - float(self.previous_signal)

    @property
    def current_spread(self) -> float:
        return float(self.current_macd) - float(self.current_signal)

    def to_position_target(self) -> PositionTargetV2:
        return PositionTargetV2(
            market_id=int(self.market_id),
            market_name=self.market_name,
            direction=self.target_direction,
            target_fraction=float(self.target_fraction),
            budget_amount=float(self.budget_amount),
            budget_currency=self.budget_currency,
            strategy_key=self.strategy_key,
            signal_at=self.signal_at,
            rationale=(
                f"confirmed closed 30m MACD 12/26/9 {self.signal}; "
                f"target {self.target_direction}"
            ),
            source_fingerprint=self.event_id,
        )


def _cross_signal_v2(previous: MacdObservationV2, current: MacdObservationV2) -> str | None:
    if previous.spread <= 0.0 < current.spread:
        return SIGNAL_UP
    if previous.spread >= 0.0 > current.spread:
        return SIGNAL_DOWN
    return None


def macd_flip_intent_from_pair_v2(
    *,
    market_id: int,
    market_name: str,
    previous: MacdObservationV2,
    current: MacdObservationV2,
    target_fraction: float,
    budget_amount: float,
    budget_currency: str = "NOK",
) -> MacdFlipIntentV2 | None:
    """Convert exactly one confirmed closed-bar cross into an immutable intent."""
    signal = _cross_signal_v2(previous, current)
    if signal is None:
        return None
    target_direction = DIRECTION_LONG if signal == SIGNAL_UP else DIRECTION_SHORT
    identity = (
        f"{MACD_FLIP_STRATEGY_V2}|{int(market_id)}|"
        f"{current.bar_time.isoformat()}|{signal}"
    )
    return MacdFlipIntentV2(
        event_id=str(uuid5(NAMESPACE_URL, identity)),
        market_id=int(market_id),
        market_name=market_name,
        signal_at=current.bar_time,
        signal=signal,
        target_direction=target_direction,
        previous_macd=previous.macd,
        previous_signal=previous.signal,
        current_macd=current.macd,
        current_signal=current.signal,
        target_fraction=float(target_fraction),
        budget_amount=float(budget_amount),
        budget_currency=budget_currency,
    )


def macd_flip_intents_from_points_v2(
    *,
    market_id: int,
    market_name: str,
    points: Iterable[tuple[str, float]],
    target_fraction: float,
    budget_amount: float,
    budget_currency: str = "NOK",
    after_bar_time: datetime | None = None,
) -> tuple[MacdFlipIntentV2, ...]:
    """Return closed-30m MACD cross intents, optionally after an exclusive cutoff.

    No forming 30m bar can produce an intent because this shares the established
    closed-bar builder with the existing MACD benchmark. The caller decides whether
    to consume only the latest intent after downtime; stale crossings are never
    implicitly replayed as live orders here.
    """
    bars = closed_30m_bars_v2(points, market=market_name)
    observations = macd_observations_v2(bars)
    if len(observations) < 2:
        raise ValueError("MACD flip policy requires enough closed 30m bars for MACD 12/26/9")

    intents: list[MacdFlipIntentV2] = []
    for previous, current in zip(observations, observations[1:]):
        if after_bar_time is not None and current.bar_time <= after_bar_time:
            continue
        intent = macd_flip_intent_from_pair_v2(
            market_id=market_id,
            market_name=market_name,
            previous=previous,
            current=current,
            target_fraction=target_fraction,
            budget_amount=budget_amount,
            budget_currency=budget_currency,
        )
        if intent is not None:
            intents.append(intent)
    return tuple(intents)


def plan_macd_flip_action_v2(
    *,
    current: PositionStateV2,
    intent: MacdFlipIntentV2,
) -> PositionDecisionV2:
    """Plan one lifecycle step toward a MACD flip target without pyramiding.

    Opposite live exposure is always CLOSED first. The same immutable intent may
    then be evaluated on a later cycle after Saxo confirms FLAT, at which point the
    canonical position controller returns OPEN. If the requested side is already
    held, this pilot intentionally HOLDs rather than ADD/REDUCE around price drift.
    """
    target = intent.to_position_target()
    current_direction = str(current.direction).upper()
    if current_direction == intent.target_direction and current.deployed_fraction > 1e-12:
        target = replace(target, target_fraction=float(current.deployed_fraction))
    return decide_position_action_v2(current, target)


def reentry_intent_is_fresh_v2(
    *,
    intent: MacdFlipIntentV2,
    flat_since: datetime,
) -> bool:
    """Risk-stop re-entry requires a MACD cross observed after becoming flat.

    This prevents a hard safety stop from immediately reopening from the stale MACD
    intent that preceded the stop. Normal signal-driven reversal keeps its pending
    intent separately and therefore remains CLOSE -> FLAT -> OPEN.
    """
    if flat_since.tzinfo is None:
        raise ValueError("flat_since must be timezone-aware")
    return intent.signal_at > flat_since


__all__ = [
    "MACD_FLIP_RECIPE_V2",
    "MACD_FLIP_STRATEGY_V2",
    "MacdFlipIntentV2",
    "macd_flip_intent_from_pair_v2",
    "macd_flip_intents_from_points_v2",
    "plan_macd_flip_action_v2",
    "reentry_intent_is_fresh_v2",
]
