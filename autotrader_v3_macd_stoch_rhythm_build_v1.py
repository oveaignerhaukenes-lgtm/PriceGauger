"""MACD+Stoch Rytmebygg v1: a controlled alternative to V2/V2.1.

Keep V2's 70/30 indicator, two-closed-bar initial entry and FULL FLAT
rules. Change only inventory *management*: hold at most one legal tranche in
whipsaw/unclear structure; build one more tranche only on independently
confirmed, sustained directional price structure. All computations use
already completed, contiguous 1-minute OHLC data. No Saxo calls or state.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import isfinite
from typing import Sequence

from autotrader_v3_domain import TargetInventoryV3
from autotrader_v3_macd_stoch_v2 import (
    MacdStochV2DecisionV3, macd_stoch_v2_target_v3,
)
from autotrader_v3_macd_trailing_v1 import MacdTrailingConfigV3

STRATEGY_KEY_V3 = "macd-stoch-rhythm-build-v1"

LOOKBACK_RETURNS = 12
MIN_DIRECTIONAL_EFFICIENCY = 0.60
CHOP_EFFICIENCY = 0.35
MAX_TREND_REVERSALS = 3
MIN_CHOP_REVERSALS = 6


@dataclass(frozen=True, slots=True)
class RhythmBuildEvidenceV1:
    available: bool
    efficiency: float | None
    reversals: int | None
    choppy: bool
    confirmed_direction: int  # +1 UP, -1 DOWN, 0 unconfirmed


def _utc(value) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(
        str(value).replace("Z", "+00:00")
    )
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def rhythm_build_evidence_v1(
    bars: Sequence, *, observation_time=None,
) -> RhythmBuildEvidenceV1:
    """Assess completed OHLC history; unavailable data can never authorize ADD."""
    missing = RhythmBuildEvidenceV1(False, None, None, False, 0)
    if len(bars) < LOOKBACK_RETURNS + 1:
        return missing
    recent = bars[-(LOOKBACK_RETURNS + 1):]
    try:
        stamps = [_utc(bar.bar_time) for bar in recent]
        if (observation_time is not None
                and stamps[-1] != _utc(observation_time)):
            return missing
        if any(
            later - prior != timedelta(minutes=1)
            for prior, later in zip(stamps, stamps[1:])
        ):
            return missing
        closes = [float(bar.close) for bar in recent]
        highs = [float(bar.high) for bar in recent]
        lows = [float(bar.low) for bar in recent]
        if not all(
            isfinite(x) and x > 0 for x in closes + highs + lows
        ):
            return missing
        if any(lo > hi or close < lo or close > hi
               for lo, hi, close in zip(lows, highs, closes)):
            return missing
    except (ValueError, TypeError, OverflowError, AttributeError):
        return missing

    changes = [b - a for a, b in zip(closes, closes[1:])]
    movement = sum(abs(change) for change in changes)
    efficiency = abs(closes[-1] - closes[0]) / movement if movement > 0 else 0.0
    nonzero_directions = [1 if x > 0 else -1 for x in changes if x != 0]
    reversals = sum(
        earlier != later
        for earlier, later in zip(nonzero_directions, nonzero_directions[1:])
    )
    choppy = efficiency <= CHOP_EFFICIENCY or reversals >= MIN_CHOP_REVERSALS

    confirmed_direction = 0
    if (
        not choppy
        and efficiency >= MIN_DIRECTIONAL_EFFICIENCY
        and reversals <= MAX_TREND_REVERSALS
    ):
        # Require trend continuation in PRICE and its recent high/low structure,
        # not merely two aligned MACD/Stoch scores. Neutral means one tranche.
        if (
            closes[-1] > closes[-2] > closes[-3]
            and highs[-1] > highs[-2]
            and lows[-1] > lows[-2]
        ):
            confirmed_direction = 1
        elif (
            closes[-1] < closes[-2] < closes[-3]
            and highs[-1] < highs[-2]
            and lows[-1] < lows[-2]
        ):
            confirmed_direction = -1

    return RhythmBuildEvidenceV1(
        True, round(efficiency, 6), reversals, choppy, confirmed_direction
    )


def macd_stoch_rhythm_build_target_v3(
    *,
    current_target: TargetInventoryV3,
    observation,
    previous_observation=None,
    bars: Sequence = (),
    config: MacdTrailingConfigV3 = MacdTrailingConfigV3(),
) -> MacdStochV2DecisionV3:
    """Open with V2, scale only with confirmed structure, FLAT as in V2.

    If V2 wants FLAT the entire position is exited immediately; never trail
    a long through a bearish MACD+Stoch reversal (nor the opposite).
    When rhythm becomes choppy, trim *all excess above one tranche*.
    A disallowed build cannot leak into a later bar: the V3 driver stores
    only the final policy target after this function returns.
    """
    base = macd_stoch_v2_target_v3(
        current_target=current_target,
        observation=observation,
        previous_observation=previous_observation,
        bars=bars,
        config=config,
    )
    # V2 exits always have precedence, including weak momentum / warmup.
    if base.action in {"OPPOSITE_FLAT", "WEAK_FLAT", "FLAT_WARMUP"}:
        return base

    tranche = float(config.tranche)
    current = round(float(current_target.amount) / tranche) * tranche
    current = 0.0 if abs(current) < tranche / 2 else round(current, 10)
    direction = 1 if current > 0 else -1 if current < 0 else 0
    evidence = rhythm_build_evidence_v1(
        bars, observation_time=observation.bar_time
    )

    def choose(target: float, action: str, why: str) -> MacdStochV2DecisionV3:
        return MacdStochV2DecisionV3(
            target=TargetInventoryV3(round(target, 10)),
            action=action,
            reason=base.reason + "; Rytmebygg: " + why,
            spread=base.spread,
            composite_score=base.composite_score,
            macd_component=base.macd_component,
            stoch_component=base.stoch_component,
        )

    if not evidence.available:
        # Unknown cadence or structure: do not open. Existing net position
        # can be reduced immediately, and V2's earlier FLAT remains valid.
        if abs(current) > tranche + 1e-9:
            return choose(direction * tranche, "TRIM_UNKNOWN_RHYTHM",
                          "missing, discontinuous or malformed 1m rhythm; trim to one unit")
        return choose(current, "HOLD_UNKNOWN_RHYTHM",
                      "no new exposure without contiguous closed 1m evidence")

    if evidence.choppy:
        if abs(current) > tranche + 1e-9:
            return choose(direction * tranche, "TRIM_CHOP",
                          f"chop: efficiency={evidence.efficiency:g}, reversals={evidence.reversals}; keep one unit")
        if not direction:
            return choose(0.0, "HOLD_CHOP_FLAT",
                          "chop without existing inventory: avoid entry")
        return choose(current, "HOLD_CHOP_MIN",
                      "chop: maintain only the existing smallest position")

    if not direction:
        # V2's initial 2-bar entry rule remains EXACTLY the same in non-chop.
        return base if base.action == "OPEN" else choose(
            0.0, "HOLD_FLAT", "await 2 aligned MACD+Stoch candles"
        )

    if evidence.confirmed_direction != direction:
        if abs(current) > tranche + 1e-9:
            return choose(direction * tranche, "TRIM_UNCONFIRMED",
                          "trend lost price-structure confirmation; reduce to minimum")
        return choose(current, "HOLD_MIN_UNCONFIRMED",
                      "price structure not confirmed in existing direction")

    # Unlike V2, a stable but weak score may NEVER grow inventory.
    # A V2 BUILD also requires high efficiency, low reversal count, and
    # 3 rising/falling closes with corresponding high/low continuation.
    if base.action == "BUILD":
        return base
    return choose(current, "HOLD_TREND", "confirmed trend but no fresh V2 build signal")


__all__ = [
    "STRATEGY_KEY_V3", "RhythmBuildEvidenceV1",
    "rhythm_build_evidence_v1", "macd_stoch_rhythm_build_target_v3",
    "LOOKBACK_RETURNS", "MIN_DIRECTIONAL_EFFICIENCY", "CHOP_EFFICIENCY",
]
