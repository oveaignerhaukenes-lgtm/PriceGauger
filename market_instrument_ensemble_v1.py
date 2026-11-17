"""Read-only 'market as a coupled instrument' descriptive research.

Only exact-timestamp, completed canonical 1m CLOSE prices. No interpolated
missing observations, broker actions, external feeds, database writes, or
causal claims. Frequency coherence is not proof of physical resonance.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from math import isfinite

import numpy as np
import pandas as pd


PERIODS_MIN = (4, 8, 16, 32, 64)
LEAD_HORIZONS_MIN = (1, 2, 5, 10)


def _clean_closes(series: pd.Series) -> pd.Series:
    if not isinstance(series.index, pd.DatetimeIndex):
        raise ValueError("market data must have a DatetimeIndex")
    stamps = pd.to_datetime(series.index, utc=True)
    if stamps.has_duplicates or not stamps.is_monotonic_increasing:
        raise ValueError("canonical timestamps must be unique and sorted")
    if any(x.second or x.microsecond for x in stamps):
        raise ValueError("canonical bars must begin on exact 1m boundaries")
    clean = pd.Series(pd.to_numeric(series, errors="coerce").to_numpy(dtype=float), index=stamps)
    clean = clean.where(np.isfinite(clean) & (clean > 0))
    return clean


def exact_minute_returns(closes: dict[str, pd.Series]) -> pd.DataFrame:
    """Log returns; no future fill or fake returns over a missing 1m period."""
    if not 2 <= len(closes) <= 8:
        raise ValueError("select 2–8 exact instruments")
    converted = {name: _clean_closes(series) for name, series in closes.items()}
    values = [s for s in converted.values() if not s.empty]
    if not values:
        return pd.DataFrame(columns=list(closes), dtype=float)
    start = min(s.index[0] for s in values)
    end = max(s.index[-1] for s in values)
    if end - start > timedelta(days=32):
        raise ValueError("cross-market research is limited to 32 calendar days")
    full_index = pd.date_range(start=start, end=end, freq="1min", tz="UTC")
    out = pd.DataFrame(index=full_index)
    for name, series in converted.items():
        minute_prices = series.reindex(full_index)
        out[name] = np.log(minute_prices / minute_prices.shift(1)).where(
            minute_prices.notna() & minute_prices.shift(1).notna()
        )
    return out


def _pearson(x: pd.Series, y: pd.Series, min_n: int = 100) -> tuple[int, float | None]:
    paired = pd.concat((x, y), axis=1).dropna()
    if len(paired) < min_n:
        return len(paired), None
    a, b = paired.iloc[:, 0].to_numpy(dtype=float), paired.iloc[:, 1].to_numpy(dtype=float)
    if np.std(a) < 1e-12 or np.std(b) < 1e-12:
        return len(paired), None
    return len(paired), float(np.corrcoef(a, b)[0, 1])


def spectral_coherence(x: pd.Series, y: pd.Series, *,
                       periods: tuple[int, ...] = PERIODS_MIN) -> dict:
    """Welch-like non-directional coherence on *jointly contiguous* 128m windows.

    Multiple overlapped segments estimate average cross-spectrum. Values in
    [0,1] describe repeated Fourier-phase consistency, not a future signal.
    """
    paired = pd.concat((x, y), axis=1).dropna()
    if paired.empty:
        return {"windows": 0, "coherence": {p: None for p in periods}}
    stamps = paired.index.to_series().diff().ne(pd.Timedelta(minutes=1)).cumsum()
    window = np.hanning(128)
    frequencies = np.fft.rfftfreq(128, d=1.0)
    xx = np.zeros(len(frequencies))
    yy = np.zeros(len(frequencies))
    xy = np.zeros(len(frequencies), dtype=complex)
    count = 0
    for _, block in paired.groupby(stamps, sort=False):
        if len(block) < 128:
            continue
        array = block.to_numpy(dtype=float)
        for start in range(0, len(array) - 127, 64):
            subset = array[start:start + 128]
            first = np.fft.rfft((subset[:, 0] - subset[:, 0].mean()) * window)
            second = np.fft.rfft((subset[:, 1] - subset[:, 1].mean()) * window)
            xx += np.abs(first) ** 2
            yy += np.abs(second) ** 2
            xy += first * np.conj(second)
            count += 1
    result = {}
    for period in periods:
        k = int(np.argmin(np.abs(frequencies - 1.0 / period)))
        if count < 8 or xx[k] <= 1e-20 or yy[k] <= 1e-20:
            result[period] = None
        else:
            result[period] = float(np.clip(abs(xy[k]) ** 2 / (xx[k] * yy[k]), 0, 1))
    return {"windows": count, "coherence": result}


def _predict_next_return(peer: pd.Series, tech: pd.Series, horizon: int) -> dict:
    """A(t) → Tech100 cumulative return (t+1..t+h), strict 60/40 holdout.

    No choice of a winning lag before holdout; every predeclared horizon is
    shown. Out-of-sample R² > 0 is improvement over training-only mean.
    """
    future = tech.rolling(horizon, min_periods=horizon).sum().shift(-horizon)
    paired = pd.concat((peer, future), axis=1).dropna()
    n = len(paired)
    if n < 250:
        return {"n": n, "test_r2": None, "test_corr": None, "test_up_hit_pct": None}
    x = paired.iloc[:, 0].to_numpy(dtype=float)
    y = paired.iloc[:, 1].to_numpy(dtype=float)
    split = int(n * 0.6)
    # Embargo: the last h train labels incorporate future Tech returns that
    # would otherwise overlap the first holdout target. No boundary peeking.
    xx, yy = x[:split - horizon], y[:split - horizon]
    if len(xx) < 100:
        return {"n": n, "test_r2": None, "test_corr": None, "test_up_hit_pct": None}
    if np.var(xx) < 1e-18:
        return {"n": n, "test_r2": None, "test_corr": None, "test_up_hit_pct": None}
    beta = float(np.mean((xx - xx.mean()) * (yy - yy.mean())) / np.var(xx))
    baseline = float(yy.mean())
    prediction = baseline + beta * (x[split:] - xx.mean())
    actual = y[split:]
    baseline_error = float(np.sum((actual - baseline) ** 2))
    r2 = (1 - float(np.sum((actual - prediction) ** 2)) / baseline_error
          if baseline_error > 1e-20 else None)
    corr = float(np.corrcoef(x[split:], actual)[0, 1]) if np.std(x[split:]) > 1e-12 and np.std(actual) > 1e-12 else None
    hit = float(np.mean((prediction > 0) == (actual > 0)) * 100)
    return {"n": n, "test_r2": r2, "test_corr": corr, "test_up_hit_pct": hit}


def ensemble_report(closes: dict[str, pd.Series], *, target: str) -> dict:
    """Bounded descriptive table + precommitted temporal holdout tests."""
    if target not in closes:
        raise ValueError("target must be an exact selected instrument")
    minute = exact_minute_returns(closes)
    if minute.empty:
        return {"coverage": [], "couplings": [], "leads": [], "coherence": [], "regimes": [], "factor": None}
    tech = minute[target]
    coverage = []
    for name, source in closes.items():
        source = _clean_closes(source)
        valid = source.dropna()
        coverage.append({"Instrument": name, "1m OHLC": len(valid),
                         "Første": valid.index[0] if len(valid) else None,
                         "Siste": valid.index[-1] if len(valid) else None,
                         "Gyldige returer": int(minute[name].count())})
    couplings, leads, coherence, regimes = [], [], [], []
    # Trailing 60m scale of Tech volatility is descriptive as-of information;
    # volatility quantile is estimated across all history, not used in LIVE.
    rolling_vol = tech.rolling(60, min_periods=60).std()
    vol_q75 = rolling_vol.quantile(0.75)
    for name in closes:
        if name == target:
            continue
        peer = minute[name]
        n, zero = _pearson(tech, peer)
        _, activity = _pearson(tech.abs(), peer.abs())
        couplings.append({"Instrument": name, "Felles 1m": n,
                          "Retningskorrelasjon": round(zero, 4) if zero is not None else None,
                          "Aktivitetskorrelasjon": round(activity, 4) if activity is not None else None})
        for horizon in LEAD_HORIZONS_MIN:
            measure = _predict_next_return(peer, tech, horizon)
            leads.append({"Instrument": name, "Fremover min": horizon,
                          "N": measure["n"],
                          "Test R²": round(measure["test_r2"], 5) if measure["test_r2"] is not None else None,
                          "Test korrelasjon": round(measure["test_corr"], 4) if measure["test_corr"] is not None else None,
                          "Test retning %": round(measure["test_up_hit_pct"], 2) if measure["test_up_hit_pct"] is not None else None})
        spectral = spectral_coherence(tech, peer)
        coherence.append({"Instrument": name, "128m-vinduer": spectral["windows"],
                          **{f"{period}m": round(spectral["coherence"][period], 3) if spectral["coherence"][period] is not None else None
                             for period in PERIODS_MIN}})
        both = pd.concat((tech, peer, rolling_vol), axis=1).dropna()
        if len(both) >= 240 and isfinite(vol_q75):
            first, second = both.iloc[:len(both)//2], both.iloc[len(both)//2:]
            high = both[both.iloc[:, 2] >= vol_q75]
            low = both[both.iloc[:, 2] < vol_q75]
            _, a = _pearson(first.iloc[:, 0], first.iloc[:, 1], min_n=80)
            _, b = _pearson(second.iloc[:, 0], second.iloc[:, 1], min_n=80)
            _, c = _pearson(high.iloc[:, 0], high.iloc[:, 1], min_n=80)
            _, d = _pearson(low.iloc[:, 0], low.iloc[:, 1], min_n=80)
            regimes.append({"Instrument": name, "Tidlig korrelasjon": round(a, 3) if a is not None else None,
                            "Sen korrelasjon": round(b, 3) if b is not None else None,
                            "Høy volatilitet": round(c, 3) if c is not None else None,
                            "Lav volatilitet": round(d, 3) if d is not None else None,
                            "N høy/lav": f"{len(high)}/{len(low)}"})
    # Shared cross-market factor: only *complete overlapping* observations.
    # Never substitute missing assets with zero or backward-filled returns.
    common = minute.dropna()
    factor = None
    if len(closes) >= 3 and len(common) >= 400:
        values = common.to_numpy(dtype=float)
        std = np.std(values, axis=0)
        if np.all(std > 1e-12):
            standardized = (values - values.mean(axis=0)) / std
            covariance = np.corrcoef(standardized, rowvar=False)
            eigvals, eigvecs = np.linalg.eigh(covariance)
            idx = int(np.argmax(eigvals))
            load = eigvecs[:, idx]
            # Sign of a principal component is arbitrary; anchor at target.
            if load[list(closes).index(target)] < 0:
                load = -load
            factor = {"common_minutes": len(common),
                      "explained_pct": round(100 * eigvals[idx] / eigvals.sum(), 2),
                      "loadings": {name: round(float(value), 3) for name, value in zip(closes, load)}}
    return {"coverage": coverage, "couplings": couplings, "leads": leads,
            "coherence": coherence, "regimes": regimes, "factor": factor,
            "pair_target": target, "time_from": minute.index[0], "time_to": minute.index[-1]}
