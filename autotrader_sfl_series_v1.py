from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
import pandas as pd

from autotrader_sfl_v1 import SFL_TIMEFRAMES_V1, sfl_decision_v1, sfl_strategy_key_v1
from autotrader_shadow_benchmark_v2 import (
    BENCHMARK_MAX_1M_BARS,
    BENCHMARK_WARMUP_DAYS,
    STATE_FLAT,
    ShadowBenchmarkSeriesV2,
    ShadowEquityPointV2,
    apply_shadow_return_v2,
)
from canonical_market_bars_v2 import CanonicalMarketBarStoreV2


SFL_SERIES_VERSION_V1 = "SFL-STATE-IMPULSE-12-26-9-v2-vectorized"


def _utc(value: Any) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _one_minute_frame(bars) -> pd.DataFrame:
    rows = []
    for item in bars:
        rows.append(
            {
                "at": _utc(item.bar_time).replace(second=0, microsecond=0) + timedelta(minutes=1),
                "open": float(item.open),
                "high": float(item.high),
                "low": float(item.low),
                "close": float(item.close),
            }
        )
    frame = pd.DataFrame(rows).drop_duplicates(subset=["at"], keep="last").set_index("at").sort_index()
    return frame


def _macd_spread_on_clock(frame: pd.DataFrame, minutes: int) -> pd.Series:
    # Right-labelled completed bars only: a 20:00-20:02 bucket becomes observable at 20:02.
    closes = frame["close"].resample(
        f"{int(minutes)}min", label="right", closed="left", origin="epoch"
    ).last().dropna()
    fast = closes.ewm(span=12, adjust=False, min_periods=12).mean()
    slow = closes.ewm(span=26, adjust=False, min_periods=26).mean()
    macd = fast - slow
    signal = macd.ewm(span=9, adjust=False, min_periods=9).mean()
    spread = macd - signal
    return spread.reindex(frame.index, method="ffill")


def _price_features(frame: pd.DataFrame) -> pd.DataFrame:
    close = frame["close"]
    delta = close.diff()
    scale = delta.abs().rolling(30, min_periods=8).median().replace(0.0, np.nan)
    impulse = ((close - close.shift(3)) / (scale * 3.0)).clip(-2.0, 2.0).fillna(0.0)

    travel = delta.abs().rolling(8, min_periods=4).sum()
    net = delta.rolling(8, min_periods=4).sum().abs()
    efficiency = (net / travel.replace(0.0, np.nan)).clip(0.0, 1.0).fillna(0.0)
    signs = np.sign(delta)
    flip = ((signs != signs.shift(1)) & (signs != 0) & (signs.shift(1) != 0)).astype(float)
    flip_noise = flip.rolling(7, min_periods=3).mean().fillna(0.0)
    noise = (0.65 * (1.0 - efficiency) + 0.35 * flip_noise).clip(0.0, 1.0)

    prior_high = close.shift(1).rolling(8, min_periods=4).max()
    prior_low = close.shift(1).rolling(8, min_periods=4).min()
    width = (prior_high - prior_low).where((prior_high - prior_low) > scale, scale).replace(0.0, np.nan)
    midpoint = (prior_high + prior_low) / 2.0
    structure = ((close - midpoint) / (width / 2.0)).clip(-1.0, 1.0).fillna(0.0)
    above = close > prior_high
    below = close < prior_low
    structure = structure.mask(above, (0.5 + (close - prior_high) / width).clip(upper=1.0))
    structure = structure.mask(below, (-0.5 - (prior_low - close) / width).clip(lower=-1.0))
    return pd.DataFrame({"impulse": impulse, "noise": noise, "structure": structure}, index=frame.index)


def _series(frame: pd.DataFrame, *, minutes: int, seed_equity: float, currency: str, started_at: datetime, as_of: datetime) -> ShadowBenchmarkSeriesV2 | None:
    spread = _macd_spread_on_clock(frame, minutes)
    features = _price_features(frame)
    working = frame.join(features).assign(spread=spread)
    working = working.loc[(working.index >= started_at) & (working.index <= as_of)]
    if working.empty:
        return None

    # Preserve up to 24 pre-start MACD observations for robust local normalization.
    full_spread = spread.dropna()
    state = STATE_FLAT
    equity = float(seed_equity)
    previous_price: float | None = None
    points: list[ShadowEquityPointV2] = []
    for at, row in working.iterrows():
        price = float(row["close"])
        if previous_price is not None and previous_price > 0.0:
            equity = apply_shadow_return_v2(
                equity=equity,
                position_state=state,
                price_return=(price / previous_price) - 1.0,
            )
        history = full_spread.loc[:at].tail(24)
        if len(history) >= 4 and pd.notna(row["spread"]):
            decision = sfl_decision_v1(
                current=state,
                spreads=tuple(float(value) for value in history),
                impulse=float(row["impulse"]),
                noise=float(row["noise"]),
                structure=float(row["structure"]),
            )
            state = decision.target
        points.append(
            ShadowEquityPointV2(
                closed_at=_utc(at.to_pydatetime()),
                equity=float(equity),
                position_state=state,
            )
        )
        previous_price = price
    return ShadowBenchmarkSeriesV2(
        strategy_key=sfl_strategy_key_v1(minutes),
        execution_mode="SHADOW_ADAPTIVE",
        currency=str(currency),
        seed_equity=float(seed_equity),
        started_at=points[0].closed_at,
        points=tuple(points),
    )


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
    # Compute shared price features once, then only the MACD clock varies by horizon.
    result = []
    for minutes in SFL_TIMEFRAMES_V1:
        spread = _macd_spread_on_clock(frame, minutes)
        working = frame.join(features).assign(spread=spread)
        window = working.loc[(working.index >= start) & (working.index <= end)]
        if window.empty:
            continue
        full_spread = spread.dropna()
        state = STATE_FLAT
        equity = float(seed_equity)
        previous_price: float | None = None
        points: list[ShadowEquityPointV2] = []
        for at, row in window.iterrows():
            price = float(row["close"])
            if previous_price is not None and previous_price > 0.0:
                equity = apply_shadow_return_v2(
                    equity=equity,
                    position_state=state,
                    price_return=(price / previous_price) - 1.0,
                )
            history = full_spread.loc[:at].tail(24)
            if len(history) >= 4 and pd.notna(row["spread"]):
                state = sfl_decision_v1(
                    current=state,
                    spreads=tuple(float(value) for value in history),
                    impulse=float(row["impulse"]),
                    noise=float(row["noise"]),
                    structure=float(row["structure"]),
                ).target
            points.append(ShadowEquityPointV2(closed_at=_utc(at.to_pydatetime()), equity=float(equity), position_state=state))
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
