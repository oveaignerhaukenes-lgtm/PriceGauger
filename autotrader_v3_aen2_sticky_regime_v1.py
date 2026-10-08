from __future__ import annotations

"""Aen#2: sticky MACD regime with fast histogram scaling.

Design learned from the first live V3 experiments:
- R timeframe owns directional authority.
- S timeframe may build quickly with the authorised regime.
- A single adverse S impulse is noise: HOLD.
- Reduction requires persistent adverse S slope *and* a weakening R spread.
- R inside a small adaptive deadband pauses new decisions and preserves inventory.
- A confirmed R regime on the opposite side forces FLAT before any reversal.

The strategy is deliberately deterministic and reconstructs R/S history from
canonical 1m bars. It does not add a separate mutable strategy-memory table.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import median
from typing import Sequence

from autotrader_mtf_entry_shadow_v2 import closed_bars_v2, macd_observations_v2
from autotrader_v3_domain import TargetInventoryV3
from autotrader_v3_macd_histogram_v1 import (
    MacdHistogramConfigV3,
    MacdHistogramDecisionV3,
)

STRATEGY_KEY_V3 = "aen2-sticky-regime-v1"

REGIME_BULL = "BULL"
REGIME_NEUTRAL = "NEUTRAL"
REGIME_BEAR = "BEAR"
REGIME_UNKNOWN = "UNKNOWN"

REGIME_SCALE_LOOKBACK_V3 = 20
REGIME_DEADBAND_FRACTION_V3 = 0.15
MIN_REGIME_OBSERVATIONS_V3 = 3
MIN_SIGNAL_OBSERVATIONS_V3 = 3


@dataclass(frozen=True, slots=True)
class StickyRegimeSnapshotV3:
    regime: str
    spread: float | None
    previous_spread: float | None
    deadband: float | None
    weakening: bool
    timeframe_minutes: int


@dataclass(frozen=True, slots=True)
class StickySignalSnapshotV3:
    spread: float | None
    previous_spread: float | None
    previous_previous_spread: float | None
    favorable_bull: bool
    favorable_bear: bool
    persistent_adverse_bull: bool
    persistent_adverse_bear: bool
    timeframe_minutes: int


def _utc(value) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(
        str(value).replace("Z", "+00:00")
    )
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _q(value: float, tranche: float) -> float:
    quantized = round(float(value) / float(tranche)) * float(tranche)
    return 0.0 if abs(quantized) < float(tranche) / 2.0 else quantized


def _observations_v3(
    *,
    source_bars: Sequence,
    closed_at,
    timeframe_minutes: int,
    market_name: str,
):
    cutoff = _utc(closed_at)
    points = tuple(
        item.point
        for item in source_bars
        if _utc(item.bar_time) < cutoff
    )
    if not points:
        return ()
    closed = closed_bars_v2(
        points,
        market=str(market_name),
        timeframe_minutes=int(timeframe_minutes),
    )
    if not closed:
        return ()
    return tuple(
        item
        for item in macd_observations_v2(
            closed,
            timeframe_minutes=int(timeframe_minutes),
        )
        if _utc(item.closed_at) <= cutoff
    )


def classify_sticky_regime_v3(
    *,
    source_bars: Sequence,
    closed_at,
    regime_timeframe_minutes: int,
    market_name: str,
) -> StickyRegimeSnapshotV3:
    observations = _observations_v3(
        source_bars=source_bars,
        closed_at=closed_at,
        timeframe_minutes=int(regime_timeframe_minutes),
        market_name=market_name,
    )
    if len(observations) < MIN_REGIME_OBSERVATIONS_V3:
        return StickyRegimeSnapshotV3(
            REGIME_UNKNOWN, None, None, None, False, int(regime_timeframe_minutes)
        )

    current = float(observations[-1].spread)
    previous = float(observations[-2].spread)
    recent = tuple(
        abs(float(item.spread))
        for item in observations[-REGIME_SCALE_LOOKBACK_V3:]
        if abs(float(item.spread)) > 1e-12
    )
    scale = median(recent) if recent else 0.0
    deadband = max(1e-9, scale * REGIME_DEADBAND_FRACTION_V3)

    if current > deadband:
        regime = REGIME_BULL
        weakening = current < previous
    elif current < -deadband:
        regime = REGIME_BEAR
        weakening = current > previous
    else:
        regime = REGIME_NEUTRAL
        weakening = False

    return StickyRegimeSnapshotV3(
        regime=regime,
        spread=current,
        previous_spread=previous,
        deadband=deadband,
        weakening=weakening,
        timeframe_minutes=int(regime_timeframe_minutes),
    )


def classify_sticky_signal_v3(
    *,
    source_bars: Sequence,
    closed_at,
    signal_timeframe_minutes: int,
    market_name: str,
) -> StickySignalSnapshotV3:
    observations = _observations_v3(
        source_bars=source_bars,
        closed_at=closed_at,
        timeframe_minutes=int(signal_timeframe_minutes),
        market_name=market_name,
    )
    if len(observations) < MIN_SIGNAL_OBSERVATIONS_V3:
        return StickySignalSnapshotV3(
            None, None, None, False, False, False, False,
            int(signal_timeframe_minutes),
        )

    previous_previous = float(observations[-3].spread)
    previous = float(observations[-2].spread)
    current = float(observations[-1].spread)

    return StickySignalSnapshotV3(
        spread=current,
        previous_spread=previous,
        previous_previous_spread=previous_previous,
        favorable_bull=current > previous,
        favorable_bear=current < previous,
        persistent_adverse_bull=current < previous < previous_previous,
        persistent_adverse_bear=current > previous > previous_previous,
        timeframe_minutes=int(signal_timeframe_minutes),
    )


def _action(current: float, target: float) -> str:
    if target == current:
        return "HOLD"
    if target == 0.0:
        return "FLAT"
    if current == 0.0:
        return "OPEN"
    if (current > 0.0) != (target > 0.0):
        return "CROSS_ZERO"
    return "BUILD" if abs(target) > abs(current) else "REDUCE"


def aen2_sticky_regime_target_v3(
    *,
    current_target: TargetInventoryV3,
    observation,
    previous_observation=None,
    source_bars: Sequence = (),
    regime_timeframe_minutes: int = 15,
    market_name: str = "",
    config: MacdHistogramConfigV3 = MacdHistogramConfigV3(),
) -> MacdHistogramDecisionV3:
    """Return one sticky R/S target transition on a newly closed S bar."""

    del previous_observation  # Full S history is reconstructed deterministically.

    current = _q(current_target.amount, config.tranche)
    tranche = float(config.tranche)
    maximum = float(config.max_inventory)
    closed_at = getattr(observation, "closed_at", observation.bar_time)
    signal_minutes = int(getattr(observation, "timeframe_minutes", 0) or 0)

    regime = classify_sticky_regime_v3(
        source_bars=source_bars,
        closed_at=closed_at,
        regime_timeframe_minutes=int(regime_timeframe_minutes),
        market_name=str(market_name),
    )
    signal = classify_sticky_signal_v3(
        source_bars=source_bars,
        closed_at=closed_at,
        signal_timeframe_minutes=signal_minutes if signal_minutes > 0 else 1,
        market_name=str(market_name),
    )

    if regime.regime == REGIME_UNKNOWN or signal.spread is None:
        target = current
        policy = "R/S history unavailable -> HOLD"
    elif regime.regime == REGIME_NEUTRAL:
        target = current
        policy = "R inside deadband -> sticky HOLD; no new build"
    elif regime.regime == REGIME_BULL:
        if current < 0.0:
            target = 0.0
            policy = "confirmed R BULL forbids SHORT -> FLAT"
        elif signal.favorable_bull:
            target = min(maximum, current + tranche)
            policy = "R BULL + S improving -> BUILD LONG"
        elif current > 0.0 and signal.persistent_adverse_bull and regime.weakening:
            target = max(0.0, current - tranche)
            policy = "two adverse S slopes + weakening R BULL -> REDUCE LONG"
        else:
            target = current
            policy = "R BULL + unconfirmed adverse S -> sticky HOLD"
    else:  # REGIME_BEAR
        if current > 0.0:
            target = 0.0
            policy = "confirmed R BEAR forbids LONG -> FLAT"
        elif signal.favorable_bear:
            target = max(-maximum, current - tranche)
            policy = "R BEAR + S weakening -> BUILD SHORT"
        elif current < 0.0 and signal.persistent_adverse_bear and regime.weakening:
            target = min(0.0, current + tranche)
            policy = "two adverse S slopes + weakening R BEAR -> REDUCE SHORT"
        else:
            target = current
            policy = "R BEAR + unconfirmed adverse S -> sticky HOLD"

    target = _q(max(-maximum, min(maximum, target)), tranche)
    r_spread = "n/a" if regime.spread is None else f"{regime.spread:+.6g}"
    r_deadband = "n/a" if regime.deadband is None else f"{regime.deadband:.6g}"
    s_spread = "n/a" if signal.spread is None else f"{signal.spread:+.6g}"
    reason = (
        f"Aen#2 R{regime.timeframe_minutes}m={regime.regime} "
        f"spread={r_spread} deadband={r_deadband}; "
        f"S{signal.timeframe_minutes}m={s_spread}; {policy}"
    )
    return MacdHistogramDecisionV3(
        target=TargetInventoryV3(target),
        action=_action(current, target),
        reason=reason,
        histogram=float(observation.spread),
    )


__all__ = [
    "STRATEGY_KEY_V3",
    "StickyRegimeSnapshotV3",
    "StickySignalSnapshotV3",
    "classify_sticky_regime_v3",
    "classify_sticky_signal_v3",
    "aen2_sticky_regime_target_v3",
]
