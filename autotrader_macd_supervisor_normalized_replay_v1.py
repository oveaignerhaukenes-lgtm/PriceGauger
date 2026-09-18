from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

import pandas as pd

from autotrader_macd_supervisor_replay_v1 import (
    SUPERVISOR_WARMUP_1M_ROWS_V1,
    MacdSupervisorReplaySummaryV1,
    summarize_macd_supervisor_frame_v1,
)
from autotrader_macd_supervisor_v1 import AUTHORITATIVE_CROSS_TIMEFRAME_V1, TIMEFRAMES_V1
from canonical_market_bars_v2 import CanonicalMarketBarV2


NORMALIZATION_SPAN_BARS_V1 = 40
NORMALIZATION_MIN_BARS_V1 = 8


@dataclass(frozen=True, slots=True)
class NormalizedMacdTimeframeStateV1:
    minutes: int
    strength: float
    previous_strength: float

    @property
    def direction(self) -> int:
        return 1 if self.strength > 0.0 else -1 if self.strength < 0.0 else 0

    @property
    def slope(self) -> float:
        return self.strength - self.previous_strength


@dataclass(frozen=True, slots=True)
class NormalizedMacdSupervisorDecisionV1:
    target: int
    score: float
    confidence: float
    context_score: float
    change_score: float
    explanation: str


@dataclass(frozen=True, slots=True)
class NormalizedMacdSupervisorSwitchV1:
    at: pd.Timestamp
    price: float
    previous_target: int
    target: int
    score: float
    confidence: float
    context_score: float
    change_score: float
    explanation: str
    strengths: dict[int, float]
    slopes: dict[int, float]


def _macd_spread(close: pd.Series) -> pd.Series:
    fast = close.ewm(span=12, adjust=False).mean()
    slow = close.ewm(span=26, adjust=False).mean()
    macd = fast - slow
    signal = macd.ewm(span=9, adjust=False).mean()
    return macd - signal


def _normalize_spread_history(spread: pd.Series) -> pd.Series:
    """Normalize one timeframe against its own prior MACD-spread magnitude.

    The existing supervisor compares raw MACD spread magnitudes across timeframes.
    Those magnitudes are not commensurate: a 30m MACD spread naturally tends to be
    numerically larger than a 1m spread even when the 1m move is locally extreme.

    This shadow normalizer therefore scales each timeframe only against its own
    historical absolute spread. The baseline is shifted one observation so the
    current move cannot dilute its own normalization denominator. A bounded ratio
    keeps every timeframe on a comparable [-1, +1] scale without look-ahead.
    """
    absolute = spread.abs()
    shifted = absolute.shift(1)
    scale = shifted.ewm(
        span=NORMALIZATION_SPAN_BARS_V1,
        adjust=False,
        min_periods=NORMALIZATION_MIN_BARS_V1,
    ).mean()
    fallback = shifted.expanding(min_periods=3).mean()
    scale = scale.combine_first(fallback).astype("float64")
    scale = scale.mask(scale <= 1e-12)
    ratio = spread.astype("float64") / scale
    bounded = ratio / (1.0 + ratio.abs())
    return bounded.astype("float64")


def _timeframe_strength(frame: pd.DataFrame, minutes: int) -> pd.Series:
    if int(minutes) == 1:
        native_close = frame["close"]
    else:
        native_close = (
            frame["close"]
            .resample(f"{int(minutes)}min", origin="epoch", label="right", closed="left")
            .last()
            .dropna()
        )
    native_strength = _normalize_spread_history(_macd_spread(native_close))
    return native_strength.reindex(frame.index, method="ffill")


def evaluate_normalized_macd_supervisor_v1(
    states: Mapping[int, NormalizedMacdTimeframeStateV1],
    *,
    current_target: int = 0,
    switch_threshold: float = 0.22,
) -> NormalizedMacdSupervisorDecisionV1:
    """Evaluate the existing supervisor idea on commensurate timeframe strengths.

    Weighting and reversal semantics intentionally stay close to supervisor v1 so
    the shadow comparison isolates normalization rather than silently introducing a
    second strategy design at the same time.
    """
    missing = [minutes for minutes in TIMEFRAMES_V1 if minutes not in states]
    if missing:
        raise ValueError(f"normalized MACD supervisor missing timeframes: {missing}")

    context_weights = {30: 0.50, 15: 0.30, 10: 0.15, 5: 0.05}
    context = sum(states[m].strength * weight for m, weight in context_weights.items())

    change_weights = {1: 0.08, 2: 0.17, 5: 0.35, 10: 0.30, 15: 0.10}
    directional_change = 0.0
    for minutes, weight in change_weights.items():
        state = states[minutes]
        slope_direction = 1.0 if state.slope > 0.0 else -1.0 if state.slope < 0.0 else 0.0
        directional_change += weight * ((0.65 * state.strength) + (0.35 * slope_direction))

    cascade = 0.0
    d1, d2, d5, d10 = (states[m].direction for m in (1, 2, 5, 10))
    if d1 != 0 and d1 == d2 == d5:
        cascade = 0.18 * d1
        if d10 == d1:
            cascade += 0.12 * d1

    score = max(-1.0, min(1.0, (0.58 * context) + (0.42 * directional_change) + cascade))
    threshold = max(0.05, min(0.75, float(switch_threshold)))
    if score > threshold:
        proposed = 1
    elif score < -threshold:
        proposed = -1
    else:
        proposed = current_target if current_target in (-1, 1) else 0

    slow_direction = 1 if context > 0.30 else -1 if context < -0.30 else 0
    if current_target == slow_direction and proposed == -slow_direction and abs(directional_change) < 0.45:
        proposed = current_target

    primary = states[AUTHORITATIVE_CROSS_TIMEFRAME_V1]
    authoritative_cross = 0
    if primary.previous_strength <= 0.0 < primary.strength:
        authoritative_cross = 1
    elif primary.previous_strength >= 0.0 > primary.strength:
        authoritative_cross = -1
    if authoritative_cross in (-1, 1):
        proposed = authoritative_cross

    confidence = min(1.0, abs(score))
    target_word = "LONG" if proposed > 0 else "SHORT" if proposed < 0 else "HOLD"
    context_word = "bullish" if context > 0.10 else "bearish" if context < -0.10 else "mixed"
    change_word = "up" if directional_change > 0.10 else "down" if directional_change < -0.10 else "unclear"
    cross_word = (
        f"; authoritative {AUTHORITATIVE_CROSS_TIMEFRAME_V1}m CROSS_"
        f"{'UP' if authoritative_cross > 0 else 'DOWN'}"
        if authoritative_cross
        else ""
    )
    explanation = (
        f"{target_word}: normalized slow context {context_word} ({context:+.2f}); "
        f"normalized fast/mid propagation {change_word} ({directional_change:+.2f}); "
        f"cascade {cascade:+.2f}; total {score:+.2f}{cross_word}."
    )
    return NormalizedMacdSupervisorDecisionV1(
        target=int(proposed),
        score=float(score),
        confidence=float(confidence),
        context_score=float(context),
        change_score=float(directional_change),
        explanation=explanation,
    )


def replay_normalized_macd_supervisor_v1(
    bars: Sequence[CanonicalMarketBarV2],
    *,
    cost_bps_per_leg: float = 0.0,
    switch_threshold: float = 0.22,
) -> tuple[pd.DataFrame, tuple[NormalizedMacdSupervisorSwitchV1, ...], MacdSupervisorReplaySummaryV1]:
    """Replay the normalized supervisor on canonical 1m data, analysis-only."""
    if len(bars) <= SUPERVISOR_WARMUP_1M_ROWS_V1:
        raise ValueError(
            f"Normalized MACD Supervisor needs >{SUPERVISOR_WARMUP_1M_ROWS_V1} canonical 1m bars for warmup"
        )

    ordered = sorted(bars, key=lambda item: item.bar_time)
    frame = pd.DataFrame(
        {
            "at": [pd.Timestamp(item.bar_time) + pd.Timedelta(minutes=1) for item in ordered],
            "close": [float(item.close) for item in ordered],
        }
    ).set_index("at")
    frame = frame[~frame.index.duplicated(keep="last")].sort_index()

    strengths = {minutes: _timeframe_strength(frame, minutes) for minutes in TIMEFRAMES_V1}
    result = pd.DataFrame(index=frame.index)
    result["PRICE"] = frame["close"]
    target = 0
    targets: list[int] = []
    scores: list[float] = []
    confidence: list[float] = []
    switches: list[NormalizedMacdSupervisorSwitchV1] = []

    for index in range(len(frame)):
        ready = index >= SUPERVISOR_WARMUP_1M_ROWS_V1 and index > 0
        if ready:
            ready = all(
                not pd.isna(strengths[m].iloc[index]) and not pd.isna(strengths[m].iloc[index - 1])
                for m in TIMEFRAMES_V1
            )
        if not ready:
            targets.append(target)
            scores.append(0.0)
            confidence.append(0.0)
            continue

        states = {
            minutes: NormalizedMacdTimeframeStateV1(
                minutes=minutes,
                strength=float(strengths[minutes].iloc[index]),
                previous_strength=float(strengths[minutes].iloc[index - 1]),
            )
            for minutes in TIMEFRAMES_V1
        }
        decision = evaluate_normalized_macd_supervisor_v1(
            states,
            current_target=target,
            switch_threshold=switch_threshold,
        )
        previous = target
        target = int(decision.target)
        if target != previous and target in (-1, 1):
            switches.append(
                NormalizedMacdSupervisorSwitchV1(
                    at=pd.Timestamp(frame.index[index]),
                    price=float(frame["close"].iloc[index]),
                    previous_target=previous,
                    target=target,
                    score=float(decision.score),
                    confidence=float(decision.confidence),
                    context_score=float(decision.context_score),
                    change_score=float(decision.change_score),
                    explanation=decision.explanation,
                    strengths={m: float(states[m].strength) for m in TIMEFRAMES_V1},
                    slopes={m: float(states[m].slope) for m in TIMEFRAMES_V1},
                )
            )
        targets.append(target)
        scores.append(float(decision.score))
        confidence.append(float(decision.confidence))

    result["TARGET"] = pd.Series(targets, index=result.index, dtype="float64")
    result["SCORE"] = pd.Series(scores, index=result.index, dtype="float64")
    result["CONFIDENCE"] = pd.Series(confidence, index=result.index, dtype="float64")
    for minutes in TIMEFRAMES_V1:
        result[f"STRENGTH_{minutes}M"] = strengths[minutes].astype("float64")

    summary = summarize_macd_supervisor_frame_v1(result, cost_bps_per_leg=cost_bps_per_leg)
    return result, tuple(switches), summary


__all__ = [
    "NORMALIZATION_MIN_BARS_V1",
    "NORMALIZATION_SPAN_BARS_V1",
    "NormalizedMacdSupervisorDecisionV1",
    "NormalizedMacdSupervisorSwitchV1",
    "NormalizedMacdTimeframeStateV1",
    "evaluate_normalized_macd_supervisor_v1",
    "replay_normalized_macd_supervisor_v1",
]
