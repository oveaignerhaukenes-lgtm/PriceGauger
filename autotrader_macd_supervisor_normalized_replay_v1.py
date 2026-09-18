from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

import pandas as pd

from autotrader_macd_supervisor_replay_v1 import (
    SUPERVISOR_WARMUP_1M_ROWS_V1,
    MacdSupervisorReplaySummaryV1,
    summarize_macd_supervisor_frame_v1,
)
from autotrader_macd_supervisor_v1 import TIMEFRAMES_V1
from canonical_market_bars_v2 import CanonicalMarketBarV2


NORMALIZATION_SPAN_BARS_V1 = 40
NORMALIZATION_MIN_BARS_V1 = 8

# Shadow-only large-move escape. These values are intentionally volatility-aware:
# a stale slow regime must not keep an opposite position through a persistent,
# locally exceptional move once 1m/2m/5m MACD agree on the new direction.
LARGE_MOVE_ESCAPE_WINDOW_BARS_V1 = 12
LARGE_MOVE_ESCAPE_VOL_LOOKBACK_BARS_V1 = 30
LARGE_MOVE_ESCAPE_MIN_RETURN_V1 = 0.0015
LARGE_MOVE_ESCAPE_VOL_MULTIPLE_V1 = 1.75
LARGE_MOVE_ESCAPE_MIN_ALIGNED_FRACTION_V1 = 0.58
LARGE_MOVE_ESCAPE_MIN_FAST_STRENGTH_V1 = 0.20


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


def _large_move_escape_direction_v1(
    close: pd.Series,
    index: int,
    states: Mapping[int, NormalizedMacdTimeframeStateV1],
    *,
    current_target: int,
) -> tuple[int, float, float]:
    """Return a bounded counter-regime escape direction, move and threshold.

    This is deliberately not another entry model. It only applies when an existing
    LONG/SHORT target is opposite a sustained, statistically material price move and
    the fast 1m/2m/5m normalized MACD states unanimously agree with that move.
    """
    current = int(current_target)
    window = int(LARGE_MOVE_ESCAPE_WINDOW_BARS_V1)
    if current not in (-1, 1) or int(index) < window:
        return 0, 0.0, float(LARGE_MOVE_ESCAPE_MIN_RETURN_V1)

    prices = close.astype("float64")
    start_price = float(prices.iloc[index - window])
    end_price = float(prices.iloc[index])
    if start_price <= 0.0 or end_price <= 0.0:
        return 0, 0.0, float(LARGE_MOVE_ESCAPE_MIN_RETURN_V1)

    move_return = (end_price / start_price) - 1.0
    move_direction = 1 if move_return > 0.0 else -1 if move_return < 0.0 else 0

    returns = prices.pct_change()
    vol_start = max(1, int(index) - int(LARGE_MOVE_ESCAPE_VOL_LOOKBACK_BARS_V1) + 1)
    recent = returns.iloc[vol_start : int(index) + 1].dropna()
    sigma_1m = float(recent.std(ddof=0)) if len(recent) >= 5 else 0.0
    volatility_threshold = (
        float(LARGE_MOVE_ESCAPE_VOL_MULTIPLE_V1)
        * sigma_1m
        * (float(window) ** 0.5)
    )
    threshold = max(float(LARGE_MOVE_ESCAPE_MIN_RETURN_V1), volatility_threshold)

    if move_direction == 0 or move_direction == current or abs(move_return) < threshold:
        return 0, float(move_return), float(threshold)

    fast_states = tuple(states[m] for m in (1, 2, 5))
    if any(item.direction != move_direction for item in fast_states):
        return 0, float(move_return), float(threshold)
    fast_strength = sum(abs(float(item.strength)) for item in fast_states) / float(len(fast_states))
    if fast_strength < float(LARGE_MOVE_ESCAPE_MIN_FAST_STRENGTH_V1):
        return 0, float(move_return), float(threshold)

    move_slice = returns.iloc[int(index) - window + 1 : int(index) + 1].dropna()
    if len(move_slice) < max(5, window // 2):
        return 0, float(move_return), float(threshold)
    aligned = sum(
        1
        for item in move_slice
        if (float(item) > 0.0 and move_direction > 0)
        or (float(item) < 0.0 and move_direction < 0)
    )
    aligned_fraction = float(aligned) / float(len(move_slice))
    if aligned_fraction < float(LARGE_MOVE_ESCAPE_MIN_ALIGNED_FRACTION_V1):
        return 0, float(move_return), float(threshold)

    return int(move_direction), float(move_return), float(threshold)


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

    confidence = min(1.0, abs(score))
    target_word = "LONG" if proposed > 0 else "SHORT" if proposed < 0 else "HOLD"
    context_word = "bullish" if context > 0.10 else "bearish" if context < -0.10 else "mixed"
    change_word = "up" if directional_change > 0.10 else "down" if directional_change < -0.10 else "unclear"
    explanation = (
        f"{target_word}: normalized slow context {context_word} ({context:+.2f}); "
        f"normalized fast/mid propagation {change_word} ({directional_change:+.2f}); "
        f"cascade {cascade:+.2f}; total {score:+.2f}."
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
    large_move_escape: bool = False,
) -> tuple[pd.DataFrame, tuple[NormalizedMacdSupervisorSwitchV1, ...], MacdSupervisorReplaySummaryV1]:
    """Replay the normalized supervisor on canonical 1m data, analysis-only.

    Large-move escape is opt-in and shadow-only. Existing normalized behavior stays
    unchanged unless a caller explicitly enables the comparator.
    """
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
    escape_flags: list[bool] = []
    move_returns: list[float] = []
    move_thresholds: list[float] = []
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
            escape_flags.append(False)
            move_returns.append(0.0)
            move_thresholds.append(float(LARGE_MOVE_ESCAPE_MIN_RETURN_V1))
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
        escape_direction = 0
        move_return = 0.0
        move_threshold = float(LARGE_MOVE_ESCAPE_MIN_RETURN_V1)
        if large_move_escape:
            escape_direction, move_return, move_threshold = _large_move_escape_direction_v1(
                frame["close"],
                index,
                states,
                current_target=previous,
            )
        escape_triggered = (
            escape_direction in (-1, 1)
            and escape_direction == -previous
            and int(decision.target) == previous
        )
        target = int(escape_direction if escape_triggered else decision.target)
        explanation = decision.explanation
        if escape_triggered:
            explanation = (
                f"LARGE_MOVE_ESCAPE {move_return:+.3%} vs {move_threshold:.3%}; "
                f"fast 1m/2m/5m consensus -> {'LONG' if target > 0 else 'SHORT'}. "
                + explanation
            )
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
                    explanation=explanation,
                    strengths={m: float(states[m].strength) for m in TIMEFRAMES_V1},
                    slopes={m: float(states[m].slope) for m in TIMEFRAMES_V1},
                )
            )
        targets.append(target)
        scores.append(float(decision.score))
        confidence.append(float(decision.confidence))
        escape_flags.append(bool(escape_triggered))
        move_returns.append(float(move_return))
        move_thresholds.append(float(move_threshold))

    result["TARGET"] = pd.Series(targets, index=result.index, dtype="float64")
    result["SCORE"] = pd.Series(scores, index=result.index, dtype="float64")
    result["CONFIDENCE"] = pd.Series(confidence, index=result.index, dtype="float64")
    result["LARGE_MOVE_ESCAPE"] = pd.Series(escape_flags, index=result.index, dtype="bool")
    result["MOVE_RETURN"] = pd.Series(move_returns, index=result.index, dtype="float64")
    result["MOVE_THRESHOLD"] = pd.Series(move_thresholds, index=result.index, dtype="float64")
    for minutes in TIMEFRAMES_V1:
        result[f"STRENGTH_{minutes}M"] = strengths[minutes].astype("float64")

    summary = summarize_macd_supervisor_frame_v1(result, cost_bps_per_leg=cost_bps_per_leg)
    return result, tuple(switches), summary


__all__ = [
    "NORMALIZATION_MIN_BARS_V1",
    "NORMALIZATION_SPAN_BARS_V1",
    "LARGE_MOVE_ESCAPE_WINDOW_BARS_V1",
    "LARGE_MOVE_ESCAPE_VOL_LOOKBACK_BARS_V1",
    "LARGE_MOVE_ESCAPE_MIN_RETURN_V1",
    "LARGE_MOVE_ESCAPE_VOL_MULTIPLE_V1",
    "LARGE_MOVE_ESCAPE_MIN_ALIGNED_FRACTION_V1",
    "LARGE_MOVE_ESCAPE_MIN_FAST_STRENGTH_V1",
    "_large_move_escape_direction_v1",
    "NormalizedMacdSupervisorDecisionV1",
    "NormalizedMacdSupervisorSwitchV1",
    "NormalizedMacdTimeframeStateV1",
    "evaluate_normalized_macd_supervisor_v1",
    "replay_normalized_macd_supervisor_v1",
]
