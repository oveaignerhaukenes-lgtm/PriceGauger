from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

import numpy as np
import pandas as pd

from autotrader_mtf_entry_shadow_v2 import closed_bars_v2, macd_observations_v2
from canonical_market_bars_v2 import CanonicalMarketBarV2
from trading_desk import ChartBar, utc


LONG = 1
FLAT = 0
SHORT = -1


@dataclass(frozen=True, slots=True)
class PriceMacdConfigV1:
    price_fast_window: int = 3
    price_slow_window: int = 6
    price_volatility_lookback: int = 20
    price_min_slope_pct: float = 0.005
    price_volatility_fraction: float = 0.20
    gentle_slow_fraction: float = 0.65


DEFAULT_PRICE_MACD_CONFIG_V1 = PriceMacdConfigV1()


@dataclass(frozen=True, slots=True)
class PriceMacdDecisionV1:
    target: int
    state: str
    reason: str
    price_direction: int
    price_fast_slope_pct: float
    price_slow_slope_pct: float
    price_threshold_pct: float
    macd_direction: int
    macd_cross: int


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
    return (
        pd.DataFrame(rows)
        .drop_duplicates("timestamp", keep="last")
        .sort_values("timestamp")
        .set_index("timestamp")
    )


def _rolling_slope(series: pd.Series, window: int) -> pd.Series:
    n = max(2, int(window))
    x = np.arange(n, dtype="float64")
    x_mean = float(x.mean())
    denominator = float(((x - x_mean) ** 2).sum())

    def slope(values: np.ndarray) -> float:
        if len(values) != n or np.isnan(values).any():
            return float("nan")
        y = values.astype("float64")
        return float(((x - x_mean) * (y - float(y.mean()))).sum() / denominator)

    return series.rolling(n, min_periods=n).apply(slope, raw=True)


def _sign(value: float) -> int:
    if float(value) > 0.0:
        return LONG
    if float(value) < 0.0:
        return SHORT
    return FLAT


def build_price_macd_features_v1(
    bars: Sequence[CanonicalMarketBarV2 | ChartBar],
    *,
    timeframe_minutes: int,
    macd_bars: Sequence[CanonicalMarketBarV2 | ChartBar] | None = None,
    config: PriceMacdConfigV1 = DEFAULT_PRICE_MACD_CONFIG_V1,
) -> pd.DataFrame:
    minutes = int(timeframe_minutes)
    if minutes <= 0:
        raise ValueError("timeframe_minutes must be positive")
    chart_bars = tuple(_chart_bar(item) for item in bars)
    frame = _frame_from_bars(chart_bars)
    if frame.empty:
        return frame

    fast_raw = _rolling_slope(frame["close"], config.price_fast_window)
    slow_raw = _rolling_slope(frame["close"], config.price_slow_window)
    price = frame["close"].replace(0.0, np.nan)
    fast_pct = (fast_raw / price) * 100.0
    slow_pct = (slow_raw / price) * 100.0
    sigma_pct = (frame["close"].pct_change() * 100.0).rolling(
        max(5, int(config.price_volatility_lookback)),
        min_periods=min(10, max(5, int(config.price_volatility_lookback))),
    ).std(ddof=0)
    threshold = pd.concat(
        [
            pd.Series(float(config.price_min_slope_pct), index=frame.index, dtype="float64"),
            sigma_pct.fillna(0.0) * float(config.price_volatility_fraction),
        ],
        axis=1,
    ).max(axis=1)

    macd_chart_bars = tuple(
        _chart_bar(item)
        for item in (bars if macd_bars is None else macd_bars)
    )
    if not macd_chart_bars:
        raise ValueError("Price + MACD requires closed bars for MACD context")
    closed = closed_bars_v2(
        tuple((item.bar_time, float(item.close)) for item in macd_chart_bars),
        market=macd_chart_bars[0].market,
        timeframe_minutes=minutes,
    )
    observations = macd_observations_v2(closed, timeframe_minutes=minutes)
    macd_rows: list[dict[str, object]] = []
    previous = None
    for current in observations:
        cross = FLAT
        if previous is not None and current.closed_at - previous.closed_at == pd.Timedelta(minutes=minutes):
            if previous.spread <= 0.0 < current.spread:
                cross = LONG
            elif previous.spread >= 0.0 > current.spread:
                cross = SHORT
        macd_rows.append(
            {
                "timestamp": pd.Timestamp(current.closed_at),
                "MACD_SPREAD": float(current.spread),
                "MACD_DIRECTION": _sign(current.spread),
                "MACD_CROSS": int(cross),
            }
        )
        previous = current

    result = frame.copy()
    result["PRICE_FAST_SLOPE_PCT"] = fast_pct
    result["PRICE_SLOW_SLOPE_PCT"] = slow_pct
    result["PRICE_THRESHOLD_PCT"] = threshold

    if macd_rows:
        macd_frame = pd.DataFrame(macd_rows).set_index("timestamp").sort_index()
        result = pd.merge_asof(
            result.sort_index().reset_index(),
            macd_frame.reset_index(),
            on="timestamp",
            direction="backward",
        ).set_index("timestamp")
    else:
        result["MACD_SPREAD"] = np.nan
        result["MACD_DIRECTION"] = 0
        result["MACD_CROSS"] = 0
    result["MACD_DIRECTION"] = result["MACD_DIRECTION"].fillna(0).astype("int64")
    result["MACD_CROSS"] = result["MACD_CROSS"].fillna(0).astype("int64")
    return result


def _price_direction_v1(
    fast: float,
    slow: float,
    threshold: float,
    config: PriceMacdConfigV1,
) -> int:
    band = max(1e-9, float(threshold))
    gentle = band * float(config.gentle_slow_fraction)
    if fast > band and slow >= -0.25 * band:
        return LONG
    if fast < -band and slow <= 0.25 * band:
        return SHORT
    if slow > gentle and fast > 0.0:
        return LONG
    if slow < -gentle and fast < 0.0:
        return SHORT
    return FLAT


def evaluate_price_macd_row_v1(
    row: pd.Series,
    *,
    current_target: int,
    config: PriceMacdConfigV1 = DEFAULT_PRICE_MACD_CONFIG_V1,
) -> PriceMacdDecisionV1:
    required = (
        "PRICE_FAST_SLOPE_PCT",
        "PRICE_SLOW_SLOPE_PCT",
        "PRICE_THRESHOLD_PCT",
        "MACD_SPREAD",
    )
    if any(pd.isna(row.get(name)) for name in required):
        return PriceMacdDecisionV1(
            target=int(current_target),
            state="WARMUP",
            reason="insufficient price/MACD warmup",
            price_direction=FLAT,
            price_fast_slope_pct=0.0,
            price_slow_slope_pct=0.0,
            price_threshold_pct=float(config.price_min_slope_pct),
            macd_direction=FLAT,
            macd_cross=FLAT,
        )

    current = int(current_target)
    fast = float(row["PRICE_FAST_SLOPE_PCT"])
    slow = float(row["PRICE_SLOW_SLOPE_PCT"])
    threshold = float(row["PRICE_THRESHOLD_PCT"])
    price_direction = _price_direction_v1(fast, slow, threshold, config)
    macd_direction = int(row.get("MACD_DIRECTION", _sign(float(row["MACD_SPREAD"]))))
    macd_cross = int(row.get("MACD_CROSS", 0))

    target = current
    state = "HOLD"
    reason = "price neutral; no new MACD cross"

    if price_direction in (LONG, SHORT):
        target = price_direction
        state = "PRICE_AUTHORITY"
        reason = (
            f"price {'UP' if target == LONG else 'DOWN'} "
            f"(fast={fast:+.4f}%/bar slow={slow:+.4f}%/bar threshold={threshold:.4f}%)"
        )
    elif macd_cross in (LONG, SHORT):
        target = macd_cross
        state = "MACD_FALLBACK"
        reason = (
            f"price neutral; selected-timeframe MACD crossed "
            f"{'UP' if macd_cross == LONG else 'DOWN'}"
        )
    elif current == FLAT and macd_direction in (LONG, SHORT):
        # Do not fabricate immediate exposure solely because an old MACD state exists.
        # From FLAT we wait for fresh price authority or a fresh MACD cross.
        target = FLAT
        state = "WAIT_FRESH"
        reason = "price neutral and MACD state is old; wait for fresh evidence"

    return PriceMacdDecisionV1(
        target=int(target),
        state=state,
        reason=reason,
        price_direction=int(price_direction),
        price_fast_slope_pct=fast,
        price_slow_slope_pct=slow,
        price_threshold_pct=threshold,
        macd_direction=int(macd_direction),
        macd_cross=int(macd_cross),
    )


def replay_price_macd_v1(
    bars: Sequence[CanonicalMarketBarV2 | ChartBar],
    *,
    timeframe_minutes: int,
    initial_target: int = FLAT,
    config: PriceMacdConfigV1 = DEFAULT_PRICE_MACD_CONFIG_V1,
) -> pd.DataFrame:
    features = build_price_macd_features_v1(
        bars,
        timeframe_minutes=int(timeframe_minutes),
        config=config,
    )
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

    for _, row in features.iterrows():
        decision = evaluate_price_macd_row_v1(
            row,
            current_target=target,
            config=config,
        )
        target = int(decision.target)
        targets.append(target)
        states.append(decision.state)
        reasons.append(decision.reason)
        price_directions.append(decision.price_direction)

    result = features.copy()
    result["PRICE"] = result["close"].astype("float64")
    result["TARGET"] = pd.Series(targets, index=result.index, dtype="float64")
    result["STATE"] = states
    result["REASON"] = reasons
    result["PRICE_DIRECTION"] = pd.Series(price_directions, index=result.index, dtype="int64")
    return result


__all__ = [
    "DEFAULT_PRICE_MACD_CONFIG_V1",
    "FLAT",
    "LONG",
    "PriceMacdConfigV1",
    "PriceMacdDecisionV1",
    "SHORT",
    "build_price_macd_features_v1",
    "evaluate_price_macd_row_v1",
    "replay_price_macd_v1",
]
