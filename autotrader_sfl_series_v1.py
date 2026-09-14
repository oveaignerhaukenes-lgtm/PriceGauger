from __future__ import annotations

from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Any

import numpy as np
import pandas as pd

from autotrader_sfl_v1 import SFL_TIMEFRAMES_V1, sfl_strategy_key_v1
from autotrader_shadow_benchmark_v2 import (
    BENCHMARK_MAX_1M_BARS,
    BENCHMARK_WARMUP_DAYS,
    STATE_FLAT,
    STATE_LONG,
    STATE_SHORT,
    ShadowBenchmarkSeriesV2,
    ShadowEquityPointV2,
    apply_shadow_return_v2,
)
from canonical_market_bars_v2 import CanonicalMarketBarStoreV2


SFL_SERIES_VERSION_V1 = "SFL-STATE-IMPULSE-12-26-9-v3-fast"
ENTER_THRESHOLD = 0.50
FAST_ENTER_THRESHOLD = 0.32
EXIT_THRESHOLD = 0.15
NOISE_FLAT_THRESHOLD = 0.68
IMPULSE_ALERT_THRESHOLD = 0.95


def _utc(value: Any) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _clip(value: float, limit: float = 1.0) -> float:
    return max(-limit, min(limit, float(value)))


def _median_abs(values) -> float:
    clean = [abs(float(value)) for value in values if np.isfinite(value)]
    return max(1e-9, float(median(clean))) if clean else 1e-9


def _one_minute_frame(bars) -> pd.DataFrame:
    rows = [
        {
            "at": _utc(item.bar_time).replace(second=0, microsecond=0) + timedelta(minutes=1),
            "open": float(item.open),
            "high": float(item.high),
            "low": float(item.low),
            "close": float(item.close),
        }
        for item in bars
    ]
    return pd.DataFrame(rows).drop_duplicates(subset=["at"], keep="last").set_index("at").sort_index()


def _macd_spread_on_clock(frame: pd.DataFrame, minutes: int) -> pd.Series:
    # Only a completed N-minute bucket becomes visible on its right edge.
    closes = frame["close"].resample(
        f"{int(minutes)}min", label="right", closed="left", origin="epoch"
    ).last().dropna()
    fast = closes.ewm(span=12, adjust=False, min_periods=12).mean()
    slow = closes.ewm(span=26, adjust=False, min_periods=26).mean()
    macd = fast - slow
    signal = macd.ewm(span=9, adjust=False, min_periods=9).mean()
    return (macd - signal).reindex(frame.index, method="ffill")


def _price_features(frame: pd.DataFrame) -> pd.DataFrame:
    close = frame["close"]
    delta = close.diff()
    scale = delta.abs().rolling(30, min_periods=8).median().replace(0.0, np.nan)
    impulse = ((close - close.shift(3)) / (scale * 3.0)).clip(-2.0, 2.0).fillna(0.0)

    travel = delta.abs().rolling(8, min_periods=4).sum()
    net = delta.rolling(8, min_periods=4).sum().abs()
    efficiency = (net / travel.replace(0.0, np.nan)).clip(0.0, 1.0).fillna(0.0)
    signs = np.sign(delta)
    flips = ((signs != signs.shift(1)) & (signs != 0) & (signs.shift(1) != 0)).astype(float)
    flip_noise = flips.rolling(7, min_periods=3).mean().fillna(0.0)
    noise = (0.65 * (1.0 - efficiency) + 0.35 * flip_noise).clip(0.0, 1.0)

    prior_high = close.shift(1).rolling(8, min_periods=4).max()
    prior_low = close.shift(1).rolling(8, min_periods=4).min()
    raw_width = prior_high - prior_low
    width = raw_width.where(raw_width > scale, scale).replace(0.0, np.nan)
    midpoint = (prior_high + prior_low) / 2.0
    structure = ((close - midpoint) / (width / 2.0)).clip(-1.0, 1.0).fillna(0.0)
    structure = structure.mask(close > prior_high, (0.5 + (close - prior_high) / width).clip(upper=1.0))
    structure = structure.mask(close < prior_low, (-0.5 - (prior_low - close) / width).clip(lower=-1.0))
    return pd.DataFrame({"impulse": impulse, "noise": noise, "structure": structure}, index=frame.index)


def _fast_target(*, current: str, spreads, impulse: float, noise: float, structure: float) -> str:
    history = [float(value) for value in spreads if np.isfinite(value)]
    if len(history) < 4:
        return current
    scale = _median_abs(history)
    current_spread, prior, prior2 = history[-1], history[-2], history[-3]
    level = _clip(current_spread / scale)
    slopes = [history[index] - history[index - 1] for index in range(1, len(history))]
    slope_scale = _median_abs(slopes)
    slope_raw = current_spread - prior
    prior_slope = prior - prior2
    slope = _clip(slope_raw / slope_scale)
    acceleration = _clip((slope_raw - prior_slope) / slope_scale)
    impulse_norm = _clip(impulse)
    structure_norm = _clip(structure)
    noise_norm = max(0.0, min(1.0, float(noise)))
    score = _clip(
        0.30 * level
        + 0.25 * slope
        + 0.15 * acceleration
        + 0.20 * impulse_norm
        + 0.10 * structure_norm
    )
    rapid_up = impulse_norm >= IMPULSE_ALERT_THRESHOLD or (impulse_norm >= 0.70 and slope >= 0.55)
    rapid_down = impulse_norm <= -IMPULSE_ALERT_THRESHOLD or (impulse_norm <= -0.70 and slope <= -0.55)

    if current == STATE_LONG:
        return STATE_FLAT if rapid_down or score <= EXIT_THRESHOLD else STATE_LONG
    if current == STATE_SHORT:
        return STATE_FLAT if rapid_up or score >= -EXIT_THRESHOLD else STATE_SHORT
    if noise_norm >= NOISE_FLAT_THRESHOLD and abs(score) < 0.72:
        return STATE_FLAT
    if score >= ENTER_THRESHOLD or (rapid_up and score >= FAST_ENTER_THRESHOLD):
        return STATE_LONG
    if score <= -ENTER_THRESHOLD or (rapid_down and score <= -FAST_ENTER_THRESHOLD):
        return STATE_SHORT
    return STATE_FLAT


def load_sfl_series_v1(*, instrument_id: int, seed_equity: float, currency: str, started_at: datetime, as_of: datetime, db_path: str = "pricegauger.db") -> tuple[ShadowBenchmarkSeriesV2, ...]:
    start, end = _utc(started_at), _utc(as_of)
    bars = CanonicalMarketBarStoreV2(db_path).load_instrument_range(
        instrument_id=int(instrument_id),
        start=start - timedelta(days=BENCHMARK_WARMUP_DAYS),
        end=end,
        limit=BENCHMARK_MAX_1M_BARS,
    )
    if not bars:
        return ()
    frame = _one_minute_frame(bars)
    if frame.empty:
        return ()
    features = _price_features(frame)
    close_values = frame["close"].to_numpy(dtype=float)
    impulse_values = features["impulse"].to_numpy(dtype=float)
    noise_values = features["noise"].to_numpy(dtype=float)
    structure_values = features["structure"].to_numpy(dtype=float)
    index = frame.index
    start_pos = int(index.searchsorted(start, side="left"))
    end_pos = int(index.searchsorted(end, side="right"))
    if start_pos >= end_pos:
        return ()

    result = []
    for minutes in SFL_TIMEFRAMES_V1:
        spread_values = _macd_spread_on_clock(frame, minutes).to_numpy(dtype=float)
        state = STATE_FLAT
        equity = float(seed_equity)
        previous_price: float | None = None
        points: list[ShadowEquityPointV2] = []
        for pos in range(start_pos, end_pos):
            price = float(close_values[pos])
            if previous_price is not None and previous_price > 0.0:
                equity = apply_shadow_return_v2(
                    equity=equity,
                    position_state=state,
                    price_return=(price / previous_price) - 1.0,
                )
            begin = max(0, pos - 23)
            state = _fast_target(
                current=state,
                spreads=spread_values[begin : pos + 1],
                impulse=float(impulse_values[pos]),
                noise=float(noise_values[pos]),
                structure=float(structure_values[pos]),
            )
            points.append(
                ShadowEquityPointV2(
                    closed_at=_utc(index[pos].to_pydatetime()),
                    equity=float(equity),
                    position_state=state,
                )
            )
            previous_price = price
        if points:
            result.append(
                ShadowBenchmarkSeriesV2(
                    strategy_key=sfl_strategy_key_v1(minutes),
                    execution_mode="SHADOW_ADAPTIVE",
                    currency=str(currency),
                    seed_equity=float(seed_equity),
                    started_at=points[0].closed_at,
                    points=tuple(points),
                )
            )
    return tuple(result)


__all__ = ["SFL_SERIES_VERSION_V1", "load_sfl_series_v1"]
