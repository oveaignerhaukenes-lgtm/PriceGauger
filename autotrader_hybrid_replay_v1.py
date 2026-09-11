from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import timedelta
from typing import Mapping, Sequence

import pandas as pd

from autotrader_macd_models_v1 import (
    MODEL_MACD2,
    MODEL_MACD2_10,
    MODEL_MACD2_S,
    MODEL_MACD_A,
    adaptive_timeframe_v1,
    macd2_stochastic_score_v1,
    stochastic_direction_score_v1,
)
from canonical_market_bars_v2 import CanonicalMarketBarV2


MODEL_NAMES_V1 = (MODEL_MACD2, MODEL_MACD2_10, MODEL_MACD2_S, MODEL_MACD_A)
DEFAULT_WEIGHTS_V1 = {
    MODEL_MACD2: 50.0,
    MODEL_MACD2_10: 20.0,
    MODEL_MACD2_S: 30.0,
    MODEL_MACD_A: 0.0,
}


@dataclass(frozen=True, slots=True)
class HybridReplaySummaryV1:
    rows: int
    switches: Mapping[str, int]
    final_return_pct: Mapping[str, float]


def _sign(value: float) -> float:
    if pd.isna(value):
        return 0.0
    if float(value) > 0.0:
        return 1.0
    if float(value) < 0.0:
        return -1.0
    return 0.0


def _macd_spread(close: pd.Series) -> pd.Series:
    fast = close.ewm(span=12, adjust=False).mean()
    slow = close.ewm(span=26, adjust=False).mean()
    macd = fast - slow
    signal = macd.ewm(span=9, adjust=False).mean()
    return macd - signal


def _timeframe_spread(frame: pd.DataFrame, minutes: int) -> pd.Series:
    if int(minutes) == 1:
        return _macd_spread(frame["close"])
    rule = f"{int(minutes)}min"
    closed = frame["close"].resample(rule, origin="epoch", label="right", closed="left").last().dropna()
    spread = _macd_spread(closed)
    return spread.reindex(frame.index, method="ffill")


def _stochastic_score(frame: pd.DataFrame) -> pd.Series:
    low = frame["low"].rolling(14, min_periods=14).min()
    high = frame["high"].rolling(14, min_periods=14).max()
    width = (high - low).replace(0.0, pd.NA)
    k = (100.0 * (frame["close"] - low) / width).fillna(50.0)
    d = k.rolling(3, min_periods=1).mean()
    result = pd.Series(0.0, index=frame.index, dtype="float64")
    for index in range(1, len(frame)):
        result.iloc[index] = stochastic_direction_score_v1(
            previous_k=float(k.iloc[index - 1]),
            previous_d=float(d.iloc[index - 1]),
            current_k=float(k.iloc[index]),
            current_d=float(d.iloc[index]),
        )
    return result


def _normalize_weights(weights: Mapping[str, float]) -> dict[str, float]:
    positive = {name: max(0.0, float(weights.get(name, 0.0))) for name in MODEL_NAMES_V1}
    total = sum(positive.values())
    if total <= 0.0:
        raise ValueError("Hybrid Lab needs at least one positive model weight")
    return {name: value / total for name, value in positive.items()}


def _target_series(score: pd.Series, *, threshold: float) -> pd.Series:
    target = pd.Series(0.0, index=score.index, dtype="float64")
    current = 0.0
    band = max(0.0, min(1.0, float(threshold)))
    for index, value in enumerate(score):
        if not pd.isna(value):
            if float(value) > band:
                current = 1.0
            elif float(value) < -band:
                current = -1.0
        target.iloc[index] = current
    return target


def _equity_curve(
    close: pd.Series,
    target: pd.Series,
    *,
    cost_bps_per_leg: float,
) -> tuple[pd.Series, int]:
    curve = pd.Series(0.0, index=close.index, dtype="float64")
    equity = 1.0
    position = 0.0
    switches = 0
    cost = max(0.0, float(cost_bps_per_leg)) / 10_000.0
    previous_close = None
    for index in range(len(close)):
        price = float(close.iloc[index])
        if previous_close is not None and previous_close > 0.0:
            minute_return = (price / previous_close) - 1.0
            equity *= 1.0 + (position * minute_return)
        desired = float(target.iloc[index])
        if desired != position:
            legs = abs(desired - position)
            if legs > 0.0:
                equity *= max(0.0, 1.0 - (cost * legs))
                switches += 1
            position = desired
        curve.iloc[index] = (equity - 1.0) * 100.0
        previous_close = price
    return curve, switches


def replay_hybrid_models_v1(
    bars: Sequence[CanonicalMarketBarV2],
    *,
    weights: Mapping[str, float] | None = None,
    hybrid_threshold: float = 0.10,
    cost_bps_per_leg: float = 0.0,
) -> tuple[pd.DataFrame, HybridReplaySummaryV1]:
    """Replay compact models on one canonical 1m clock without broker authority.

    The result is normalized signal return before leverage. Model votes are combined
    first and only then translated into one hybrid target, matching the intended live
    hybrid architecture rather than averaging independent P/L curves.
    """
    if len(bars) < 80:
        raise ValueError("Hybrid Lab needs at least 80 canonical 1m bars")
    ordered = sorted(bars, key=lambda item: item.bar_time)
    frame = pd.DataFrame(
        {
            "at": [pd.Timestamp(item.bar_time) + pd.Timedelta(minutes=1) for item in ordered],
            "open": [float(item.open) for item in ordered],
            "high": [float(item.high) for item in ordered],
            "low": [float(item.low) for item in ordered],
            "close": [float(item.close) for item in ordered],
        }
    ).set_index("at")
    frame = frame[~frame.index.duplicated(keep="last")].sort_index()

    spread1 = _timeframe_spread(frame, 1)
    spread2 = _timeframe_spread(frame, 2)
    spread5 = _timeframe_spread(frame, 5)
    spread10 = _timeframe_spread(frame, 10)
    stoch = _stochastic_score(frame)

    macd2 = spread2.map(_sign)
    macd2_10 = pd.Series(0.0, index=frame.index, dtype="float64")
    for index in range(len(frame)):
        fast = _sign(spread2.iloc[index])
        slow = _sign(spread10.iloc[index])
        macd2_10.iloc[index] = fast if fast != 0.0 and fast == slow else 0.0

    macd2_s = pd.Series(0.0, index=frame.index, dtype="float64")
    for index in range(len(frame)):
        macd2_s.iloc[index] = macd2_stochastic_score_v1(
            spread_2m=float(spread2.iloc[index]) if not pd.isna(spread2.iloc[index]) else 0.0,
            stochastic_score=float(stoch.iloc[index]),
            stochastic_weight=0.20,
        )

    adaptive = pd.Series(0.0, index=frame.index, dtype="float64")
    outcomes: deque[bool] = deque(maxlen=8)
    crosses: dict[int, int] = {}
    for index in range(1, len(frame)):
        prior = float(spread1.iloc[index - 1])
        current = float(spread1.iloc[index])
        if prior <= 0.0 < current:
            crosses[index] = 1
        elif prior >= 0.0 > current:
            crosses[index] = -1
        origin = index - 3
        if origin in crosses:
            direction = crosses[origin]
            move = float(frame["close"].iloc[index]) - float(frame["close"].iloc[origin])
            outcomes.append((move * direction) > 0.0)
        if len(outcomes) >= 3:
            edge = sum(1 for item in outcomes if item) / float(len(outcomes))
            noise = 1.0 - edge
        else:
            edge = noise = 0.5
        minutes = adaptive_timeframe_v1(micro_edge=edge, noise=noise)
        selected = spread1 if minutes == 1 else spread5 if minutes == 5 else spread2
        adaptive.iloc[index] = _sign(selected.iloc[index])

    model_scores = {
        MODEL_MACD2: macd2,
        MODEL_MACD2_10: macd2_10,
        MODEL_MACD2_S: macd2_s,
        MODEL_MACD_A: adaptive,
    }
    normalized_weights = _normalize_weights(weights or DEFAULT_WEIGHTS_V1)
    hybrid_score = sum(model_scores[name] * normalized_weights[name] for name in MODEL_NAMES_V1)

    targets = {
        MODEL_MACD2: _target_series(macd2, threshold=0.0),
        MODEL_MACD2_10: _target_series(macd2_10, threshold=0.0),
        MODEL_MACD2_S: _target_series(macd2_s, threshold=0.65),
        MODEL_MACD_A: _target_series(adaptive, threshold=0.0),
        "HYBRID": _target_series(hybrid_score, threshold=hybrid_threshold),
    }

    result = pd.DataFrame(index=frame.index)
    switches: dict[str, int] = {}
    final: dict[str, float] = {}
    for name, target in targets.items():
        curve, count = _equity_curve(frame["close"], target, cost_bps_per_leg=cost_bps_per_leg)
        result[name] = curve
        switches[name] = count
        final[name] = float(curve.iloc[-1])
    result["HYBRID_SCORE"] = hybrid_score
    result["PRICE"] = frame["close"]
    return result, HybridReplaySummaryV1(rows=len(result), switches=switches, final_return_pct=final)


__all__ = [
    "DEFAULT_WEIGHTS_V1",
    "HybridReplaySummaryV1",
    "MODEL_NAMES_V1",
    "replay_hybrid_models_v1",
]
