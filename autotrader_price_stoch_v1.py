from __future__ import annotations

from dataclasses import dataclass
from math import atan, degrees
from typing import Iterable, Sequence

import numpy as np
import pandas as pd

from canonical_market_bars_v2 import CanonicalMarketBarV2
from trading_desk import ChartBar, utc


LONG = 1
FLAT = 0
SHORT = -1


@dataclass(frozen=True, slots=True)
class PriceStochConfigV1:
    """PG-native price-first / stochastic-scout policy.

    The stochastic angle is scale-independent with respect to chart zoom: it is
    derived from %K slope, not from rendered pixels. Price owns direction; stochastic
    can only prepare/flatten ("half-parade") before price confirms a reversal.
    """

    stochastic_period: int = 14
    stochastic_angle_scale: float = 8.0
    stochastic_scout_min_slope: float = 1.25
    price_fast_window: int = 3
    price_slow_window: int = 6
    price_volatility_lookback: int = 20
    price_min_slope_pct: float = 0.005
    price_volatility_fraction: float = 0.20
    gentle_slow_fraction: float = 0.65
    fast_reversal_multiple: float = 1.80
    half_parade_price_fraction: float = 0.25


DEFAULT_PRICE_STOCH_CONFIG_V1 = PriceStochConfigV1()


@dataclass(frozen=True, slots=True)
class PriceStochDecisionV1:
    target: int
    state: str
    reason: str
    price_direction: int
    stochastic_scout: int
    stochastic_alignment: int
    stochastic_k: float
    stochastic_slope_1: float
    stochastic_slope_3: float
    stochastic_slope_5: float
    stochastic_angle_1: float
    stochastic_angle_3: float
    stochastic_angle_5: float
    price_fast_slope_pct: float
    price_slow_slope_pct: float
    price_threshold_pct: float
    macd_spread: float
    macd_direction: int


def _chart_bar(item: CanonicalMarketBarV2 | ChartBar) -> ChartBar:
    return ChartBar(
        market=str(item.market_name if isinstance(item, CanonicalMarketBarV2) else item.market),
        bar_time=utc(item.bar_time).isoformat(),
        open=float(item.open),
        high=float(item.high),
        low=float(item.low),
        close=float(item.close),
        volume=None if item.volume is None else float(item.volume),
    )


def _frame_from_bars(
    bars: Iterable[CanonicalMarketBarV2 | ChartBar],
) -> pd.DataFrame:
    items = tuple(_chart_bar(item) for item in bars)
    if not items:
        return pd.DataFrame(columns=("open", "high", "low", "close"))
    rows = [
        {
            "timestamp": pd.Timestamp(utc(item.bar_time)),
            "open": float(item.open),
            "high": float(item.high),
            "low": float(item.low),
            "close": float(item.close),
        }
        for item in items
    ]
    frame = pd.DataFrame(rows).drop_duplicates("timestamp", keep="last").sort_values("timestamp")
    return frame.set_index("timestamp")


def _rolling_slope(series: pd.Series, window: int) -> pd.Series:
    n = int(window)
    if n <= 1:
        return series.diff()
    x = np.arange(n, dtype="float64")
    x_mean = float(x.mean())
    denominator = float(((x - x_mean) ** 2).sum())

    def slope(values: np.ndarray) -> float:
        if len(values) != n or np.isnan(values).any():
            return float("nan")
        y = values.astype("float64")
        return float(((x - x_mean) * (y - float(y.mean()))).sum() / denominator)

    return series.rolling(n, min_periods=n).apply(slope, raw=True)


def _angle(slope: float, scale: float) -> float:
    divisor = max(1e-9, abs(float(scale)))
    return degrees(atan(float(slope) / divisor))


def build_price_stoch_features_v1(
    bars: Sequence[CanonicalMarketBarV2 | ChartBar],
    *,
    config: PriceStochConfigV1 = DEFAULT_PRICE_STOCH_CONFIG_V1,
) -> pd.DataFrame:
    """Build the PG Stochastic Vector and price vector with no future data."""

    frame = _frame_from_bars(bars)
    if frame.empty:
        return frame

    period = max(2, int(config.stochastic_period))
    high = frame["high"].rolling(period, min_periods=period).max()
    low = frame["low"].rolling(period, min_periods=period).min()
    spread = high - low
    stochastic_k = (100.0 * (frame["close"] - low) / spread.replace(0.0, np.nan)).where(
        spread != 0.0,
        50.0,
    )

    slope_1 = stochastic_k.diff()
    slope_3 = _rolling_slope(stochastic_k, 3)
    slope_5 = _rolling_slope(stochastic_k, 5)

    fast_raw = _rolling_slope(frame["close"], max(2, int(config.price_fast_window)))
    slow_raw = _rolling_slope(frame["close"], max(2, int(config.price_slow_window)))
    price = frame["close"].replace(0.0, np.nan)
    fast_pct = (fast_raw / price) * 100.0
    slow_pct = (slow_raw / price) * 100.0

    return_pct = frame["close"].pct_change() * 100.0
    sigma_pct = return_pct.rolling(
        max(5, int(config.price_volatility_lookback)),
        min_periods=min(10, max(5, int(config.price_volatility_lookback))),
    ).std(ddof=0)
    threshold = pd.Series(float(config.price_min_slope_pct), index=frame.index, dtype="float64")
    threshold = pd.concat(
        [
            threshold,
            sigma_pct.fillna(0.0) * float(config.price_volatility_fraction),
        ],
        axis=1,
    ).max(axis=1)

    fast_ema = frame["close"].ewm(span=12, adjust=False, min_periods=12).mean()
    slow_ema = frame["close"].ewm(span=26, adjust=False, min_periods=26).mean()
    macd = fast_ema - slow_ema
    signal = macd.ewm(span=9, adjust=False, min_periods=9).mean()
    macd_spread = macd - signal

    result = frame.copy()
    result["STOCH_K"] = stochastic_k
    result["STOCH_SLOPE_1"] = slope_1
    result["STOCH_SLOPE_3"] = slope_3
    result["STOCH_SLOPE_5"] = slope_5
    result["STOCH_ANGLE_1"] = slope_1.apply(
        lambda value: float("nan") if pd.isna(value) else _angle(float(value), config.stochastic_angle_scale)
    )
    result["STOCH_ANGLE_3"] = slope_3.apply(
        lambda value: float("nan") if pd.isna(value) else _angle(float(value), config.stochastic_angle_scale)
    )
    result["STOCH_ANGLE_5"] = slope_5.apply(
        lambda value: float("nan") if pd.isna(value) else _angle(float(value), config.stochastic_angle_scale)
    )
    result["PRICE_FAST_SLOPE_PCT"] = fast_pct
    result["PRICE_SLOW_SLOPE_PCT"] = slow_pct
    result["PRICE_THRESHOLD_PCT"] = threshold
    result["MACD_SPREAD"] = macd_spread
    return result


def _sign(value: float, threshold: float = 0.0) -> int:
    number = float(value)
    band = max(0.0, float(threshold))
    if number > band:
        return LONG
    if number < -band:
        return SHORT
    return FLAT


def _stochastic_scout_v1(
    *,
    slope_1: float,
    slope_3: float,
    slope_5: float,
    min_slope: float,
) -> tuple[int, int]:
    """Fast %K angle is the scout; longer slope horizons express persistence."""

    minimum = max(0.0, float(min_slope))
    one = _sign(slope_1, minimum)
    three = _sign(slope_3, minimum * 0.55)
    five = _sign(slope_5, minimum * 0.35)

    scout = one if one != FLAT and three == one else FLAT
    if scout == FLAT:
        return FLAT, 0
    alignment = sum(1 for direction in (one, three, five) if direction == scout)
    return scout, alignment


def _price_direction_v1(
    *,
    fast: float,
    slow: float,
    threshold: float,
    stochastic_scout: int,
    config: PriceStochConfigV1,
) -> int:
    """Price owns direction. The stochastic scout can accelerate, never veto."""

    band = max(1e-9, float(threshold))
    gentle = band * float(config.gentle_slow_fraction)
    strong_fast = band * float(config.fast_reversal_multiple)

    if fast > band and slow >= -0.25 * band:
        return LONG
    if fast < -band and slow <= 0.25 * band:
        return SHORT

    # A persistent gentle trend is enough even before MACD follows.
    if slow > gentle and fast > 0.0:
        return LONG
    if slow < -gentle and fast < 0.0:
        return SHORT

    # Fast reversal route: price still owns the move; stochastic only supplies the
    # "half-parade" evidence that lets a large fresh price slope act promptly.
    if fast > strong_fast and stochastic_scout == LONG:
        return LONG
    if fast < -strong_fast and stochastic_scout == SHORT:
        return SHORT
    return FLAT


def evaluate_price_stoch_row_v1(
    row: pd.Series,
    *,
    current_target: int,
    config: PriceStochConfigV1 = DEFAULT_PRICE_STOCH_CONFIG_V1,
) -> PriceStochDecisionV1:
    required = (
        "STOCH_K",
        "STOCH_SLOPE_1",
        "STOCH_SLOPE_3",
        "STOCH_SLOPE_5",
        "STOCH_ANGLE_1",
        "STOCH_ANGLE_3",
        "STOCH_ANGLE_5",
        "PRICE_FAST_SLOPE_PCT",
        "PRICE_SLOW_SLOPE_PCT",
        "PRICE_THRESHOLD_PCT",
        "MACD_SPREAD",
    )
    if any(pd.isna(row.get(name)) for name in required):
        return PriceStochDecisionV1(
            target=int(current_target),
            state="WARMUP",
            reason="insufficient stochastic/price-vector warmup",
            price_direction=FLAT,
            stochastic_scout=FLAT,
            stochastic_alignment=0,
            stochastic_k=float(row.get("STOCH_K", 50.0) if not pd.isna(row.get("STOCH_K")) else 50.0),
            stochastic_slope_1=0.0,
            stochastic_slope_3=0.0,
            stochastic_slope_5=0.0,
            stochastic_angle_1=0.0,
            stochastic_angle_3=0.0,
            stochastic_angle_5=0.0,
            price_fast_slope_pct=0.0,
            price_slow_slope_pct=0.0,
            price_threshold_pct=float(row.get("PRICE_THRESHOLD_PCT", config.price_min_slope_pct)),
            macd_spread=0.0,
            macd_direction=FLAT,
        )

    current = int(current_target)
    if current not in (SHORT, FLAT, LONG):
        raise ValueError("current_target must be -1, 0 or 1")

    slope_1 = float(row["STOCH_SLOPE_1"])
    slope_3 = float(row["STOCH_SLOPE_3"])
    slope_5 = float(row["STOCH_SLOPE_5"])
    scout, alignment = _stochastic_scout_v1(
        slope_1=slope_1,
        slope_3=slope_3,
        slope_5=slope_5,
        min_slope=config.stochastic_scout_min_slope,
    )
    fast = float(row["PRICE_FAST_SLOPE_PCT"])
    slow = float(row["PRICE_SLOW_SLOPE_PCT"])
    threshold = float(row["PRICE_THRESHOLD_PCT"])
    price_direction = _price_direction_v1(
        fast=fast,
        slow=slow,
        threshold=threshold,
        stochastic_scout=scout,
        config=config,
    )

    target = current
    state = "FOLLOW_PRICE"
    reason = "price direction unchanged"

    if price_direction in (LONG, SHORT):
        target = price_direction
        if target != current:
            state = "PRICE_CONFIRMED_REVERSAL" if current in (LONG, SHORT) else "PRICE_CONFIRMED_ENTRY"
            reason = (
                f"price vector {'UP' if target == LONG else 'DOWN'} "
                f"(fast={fast:+.4f}%/bar slow={slow:+.4f}%/bar threshold={threshold:.4f}%)"
            )
        else:
            reason = (
                f"price confirms {'LONG' if target == LONG else 'SHORT'} "
                f"(fast={fast:+.4f}%/bar slow={slow:+.4f}%/bar)"
            )
    else:
        half_band = threshold * float(config.half_parade_price_fraction)
        if current == LONG and scout == SHORT and fast <= half_band and slow <= half_band:
            target = FLAT
            state = "HALF_PARADE_DOWN"
            reason = (
                f"stochastic vector turned down ({alignment}/3 horizons) while price no longer confirms LONG"
            )
        elif current == SHORT and scout == LONG and fast >= -half_band and slow >= -half_band:
            target = FLAT
            state = "HALF_PARADE_UP"
            reason = (
                f"stochastic vector turned up ({alignment}/3 horizons) while price no longer confirms SHORT"
            )
        elif current == FLAT:
            state = "HALF_PARADE_WAIT" if scout else "PRICE_NEUTRAL"
            reason = (
                f"stochastic scout {'UP' if scout == LONG else 'DOWN'} waits for price confirmation"
                if scout
                else "price and stochastic vector are neutral"
            )
        else:
            state = "HOLD_PRICE_UNCONFIRMED"
            reason = "no opposite price trend confirmed; stochastic alone cannot reverse"

    macd_spread = float(row["MACD_SPREAD"])
    macd_direction = _sign(macd_spread)
    return PriceStochDecisionV1(
        target=int(target),
        state=state,
        reason=reason,
        price_direction=int(price_direction),
        stochastic_scout=int(scout),
        stochastic_alignment=int(alignment),
        stochastic_k=float(row["STOCH_K"]),
        stochastic_slope_1=slope_1,
        stochastic_slope_3=slope_3,
        stochastic_slope_5=slope_5,
        stochastic_angle_1=float(row["STOCH_ANGLE_1"]),
        stochastic_angle_3=float(row["STOCH_ANGLE_3"]),
        stochastic_angle_5=float(row["STOCH_ANGLE_5"]),
        price_fast_slope_pct=fast,
        price_slow_slope_pct=slow,
        price_threshold_pct=threshold,
        macd_spread=macd_spread,
        macd_direction=int(macd_direction),
    )


def replay_price_stoch_v1(
    bars: Sequence[CanonicalMarketBarV2 | ChartBar],
    *,
    initial_target: int = FLAT,
    config: PriceStochConfigV1 = DEFAULT_PRICE_STOCH_CONFIG_V1,
) -> pd.DataFrame:
    """Replay the exact price-first policy used by LIVE on known bars only."""

    features = build_price_stoch_features_v1(bars, config=config)
    if features.empty:
        result = features.copy()
        result["PRICE"] = pd.Series(dtype="float64")
        result["TARGET"] = pd.Series(dtype="float64")
        return result

    target = int(initial_target)
    targets: list[int] = []
    states: list[str] = []
    reasons: list[str] = []
    price_directions: list[int] = []
    scouts: list[int] = []
    alignments: list[int] = []

    for _, row in features.iterrows():
        decision = evaluate_price_stoch_row_v1(
            row,
            current_target=target,
            config=config,
        )
        target = int(decision.target)
        targets.append(target)
        states.append(decision.state)
        reasons.append(decision.reason)
        price_directions.append(decision.price_direction)
        scouts.append(decision.stochastic_scout)
        alignments.append(decision.stochastic_alignment)

    result = features.copy()
    result["PRICE"] = result["close"].astype("float64")
    result["TARGET"] = pd.Series(targets, index=result.index, dtype="float64")
    result["STATE"] = states
    result["REASON"] = reasons
    result["PRICE_DIRECTION"] = pd.Series(price_directions, index=result.index, dtype="int64")
    result["STOCH_SCOUT"] = pd.Series(scouts, index=result.index, dtype="int64")
    result["STOCH_ALIGNMENT"] = pd.Series(alignments, index=result.index, dtype="int64")
    return result


__all__ = [
    "DEFAULT_PRICE_STOCH_CONFIG_V1",
    "FLAT",
    "LONG",
    "PriceStochConfigV1",
    "PriceStochDecisionV1",
    "SHORT",
    "build_price_stoch_features_v1",
    "evaluate_price_stoch_row_v1",
    "replay_price_stoch_v1",
]
