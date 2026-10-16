"""Read-only, causal wavelet-inspired rhythm bank and lag-correlation baseline.

Uses ONLY contiguous, fully closed 1-minute observations. No broker access,
LIVE strategy capability, database writes, or retroactive pivot signal.

The bank is a *one-sided* zero-DC complex Morlet-like filter, not a centered
continuous wavelet transform. This design trades symmetric wavelet fidelity
for the strict as-of timestamp needed to compare indicators honestly.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite, pi

import numpy as np
import pandas as pd

from autotrader_market_rhythm_v1 import confirmed_turns_v1

PERIODS_MIN = (4, 6, 8, 12, 16, 24, 32, 48, 64)
MIN_OBSERVED_CYCLES = 3
MAX_POINTS = 1600
MIN_CONFIRMATION_PCT = 0.10


@dataclass(frozen=True, slots=True)
class CycleResearchV1:
    prices: pd.Series
    normalized_power: pd.DataFrame
    dominant_wavelet_minutes: int | None
    wavelet_contrast: float | None
    lag_correlation_minutes: int | None
    lag_correlation: float | None
    confirmed_turns: tuple
    total_input_bars: int
    contiguous_bars: int
    cut_at_gap: bool


def _coerce_closes(prices: pd.Series) -> pd.Series:
    if not isinstance(prices.index, pd.DatetimeIndex):
        raise ValueError("expected DatetimeIndex of completed canonical 1-minute candles")
    series = pd.to_numeric(prices, errors="coerce").dropna()
    series = series[(series > 0) & series.map(lambda x: isfinite(float(x)))]
    if not series.index.is_monotonic_increasing or series.index.has_duplicates:
        raise ValueError("canonical one-minute timeline must be strictly increasing and unique")
    series.index = pd.to_datetime(series.index, utc=True)
    return series


def _latest_contiguous_session(prices: pd.Series) -> tuple[pd.Series, bool]:
    if prices.empty:
        return prices, False
    # A 2-minute gap or overnight halt must not masquerade as a single
    # 4-minute cycle. Never interpolate absent candles.
    diff = prices.index.to_series().diff()
    gap = diff > pd.Timedelta(seconds=90)
    start = int(np.flatnonzero(gap.to_numpy())[-1]) if gap.any() else 0
    return prices.iloc[start:].tail(MAX_POINTS), start != 0


def causal_morlet_bank_v1(
    closes: pd.Series, *,
    periods: tuple[int, ...] = PERIODS_MIN,
) -> pd.DataFrame:
    """Positive wavelet-magnitude proxy on an end-time-stamped, past-only FIR.

    The one-sided, complex tapered Fourier kernel removes a DC component and
    integrates log returns over up to 3 periods. No data after timestamp t
    contributes to the value at t. Warmup values are NaN, not zero.
    """
    series = _coerce_closes(closes)
    if not periods or any(int(p) != p or p < 4 or p > 180 for p in periods):
        raise ValueError("periods must be integer minutes in [4,180]")
    result = pd.DataFrame(index=series.index)
    if len(series) < 2:
        for period in periods:
            result[int(period)] = np.nan
        return result
    returns = np.diff(np.log(series.to_numpy(dtype=float)), prepend=np.nan)
    returns[0] = 0.0
    for period in periods:
        period = int(period)
        length = period * MIN_OBSERVED_CYCLES
        lags = np.arange(length, dtype=float)
        weights = np.exp(-0.5 * (lags / period) ** 2)
        oscillation = np.exp(2j * pi * lags / period)
        dc = np.sum(weights * oscillation) / np.sum(weights)
        kernel = weights * (oscillation - dc)
        kernel = kernel / max(np.sum(np.abs(kernel)), 1e-12)
        filtered = np.convolve(returns, kernel, mode="full")[: len(returns)]
        mag = np.abs(filtered) * 10000.0  # normalized logarithmic-return bp
        mag[:length] = np.nan  # three FULL periods; no partial warmup signal
        result[period] = mag
    return result


def latest_lag_correlation_v1(
    closes: pd.Series, *,
    periods: tuple[int, ...] = PERIODS_MIN,
) -> tuple[int | None, float | None]:
    """Independent, Ehlers-inspired (NOT Ehlers HT_DCPERIOD) ACF check.

    Compares detrended *returns* with past returns at candidate lags, using
    the same trailing sample length for every candidate to avoid selection
    based on incompatible sample size.
    """
    series = _coerce_closes(closes)
    if not periods:
        return None, None
    maximum = max(periods)
    window = min(len(series) - 1, max(4 * maximum, 160))
    if window < 4 * maximum:
        return None, None
    returns = np.diff(np.log(series.to_numpy(dtype=float)))[-window:]
    if not np.all(np.isfinite(returns)):
        return None, None
    centered = returns - np.mean(returns)
    if float(np.std(centered)) < 1e-9:
        return None, None
    scored = []
    for p in periods:
        a, b = centered[p:], centered[:-p]
        norm = float(np.linalg.norm(a) * np.linalg.norm(b))
        score = float(np.dot(a,b) / norm) if norm > 1e-12 else 0.0
        scored.append((p, score))
    best = max(scored, key=lambda item: (item[1], -item[0]))
    return (int(best[0]), float(best[1])) if best[1] >= 0.25 else (None, None)


def build_cycle_research_v1(
    prices: pd.Series,
    *,
    reversal_pct: float = MIN_CONFIRMATION_PCT,
    periods: tuple[int, ...] = PERIODS_MIN,
) -> CycleResearchV1:
    """One read-only dashboard snapshot. All completed bars are known as-of."""
    source = _coerce_closes(prices)
    clean, cut = _latest_contiguous_session(source)
    bank = causal_morlet_bank_v1(clean, periods=periods)
    latest = bank.iloc[-1].dropna() if not bank.empty else pd.Series(dtype=float)
    dominant = None
    contrast = None
    if len(latest) >= 3:
        strongest = float(latest.max())
        median_power = float(latest.median())
        if strongest > 1e-6 and median_power > 1e-9:
            contrast = strongest / median_power
            if contrast >= 1.35:
                dominant = int(latest.idxmax())
    period_acf, strength_acf = latest_lag_correlation_v1(clean, periods=periods)
    turns = confirmed_turns_v1(clean, reversal_pct=reversal_pct)
    return CycleResearchV1(
        prices=clean,
        normalized_power=bank,
        dominant_wavelet_minutes=dominant,
        wavelet_contrast=contrast,
        lag_correlation_minutes=period_acf,
        lag_correlation=strength_acf,
        confirmed_turns=turns,
        total_input_bars=len(source),
        contiguous_bars=len(clean),
        cut_at_gap=cut,
    )


__all__ = [
    "PERIODS_MIN","MIN_CONFIRMATION_PCT","CycleResearchV1",
    "causal_morlet_bank_v1","latest_lag_correlation_v1","build_cycle_research_v1",
]
