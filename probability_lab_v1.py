"""Read-only causal 1m probability research. No broker, execution or SQL writes.

All forecasts are issued after a completed 1m close. For horizon h, every
training label j->j+h must have resolved by forecast time i (j+h <= i).
Poisson/Skellam treats signed minute bars as events: a deliberately testable
proxy, NOT Poisson tick arrivals or a forecast of Saxo bid/ask execution.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import exp, isfinite, log
from typing import Sequence


LABELS = ("up", "down", "flat")
HORIZONS = (1, 2, 5, 10)
MAX_BARS = 10000


@dataclass(frozen=True)
class ProbabilityForecast:
    asof: str
    target: str | None
    horizon: int
    baseline: tuple[float, float, float]
    markov: tuple[float, float, float]
    skellam: tuple[float, float, float]
    actual: str | None
    return_pct: float | None
    sample_size: int
    state_matches: int


def _sign(delta: float) -> int:
    return 0 if abs(delta) < 1e-10 else (1 if delta > 0 else -1)


def _label(direction: int) -> str:
    return "up" if direction > 0 else "down" if direction < 0 else "flat"


def _index(direction: int) -> int:
    return 0 if direction > 0 else 1 if direction < 0 else 2


def _stamp(value: str | datetime) -> datetime:
    dt = value if isinstance(value, datetime) else datetime.fromisoformat(
        str(value).replace("Z", "+00:00")
    )
    if dt.tzinfo is None:
        raise ValueError("1m OHLC must have timezone-aware UTC timestamps")
    dt = dt.astimezone(timezone.utc)
    if dt.second or dt.microsecond:
        raise ValueError("expected completed minute-aligned 1m OHLC")
    return dt


def _segments(bars: Sequence) -> list[list[tuple[datetime, float]]]:
    if len(bars) > MAX_BARS:
        raise ValueError("too many bars for bounded research scan")
    groups: list[list[tuple[datetime, float]]] = []
    previous = None
    for bar in bars:
        at = _stamp(bar.bar_time)
        close = float(bar.close)
        if not isfinite(close) or close <= 0:
            raise ValueError("invalid 1m close")
        if previous is not None and at <= previous:
            raise ValueError("1m bars must be sorted and unique")
        if previous is None or (at - previous).total_seconds() != 60:
            groups.append([])
        groups[-1].append((at, close))
        previous = at
    return groups


def _pmf(lam: float) -> list[float]:
    # For minute-sign event intensity lam <= horizon <=10, tail < 1e-12.
    upper = max(24, int(lam + 12 * (lam + 1) ** .5))
    p = exp(-lam)
    out = [p]
    for k in range(1, upper + 1):
        p *= lam / k
        out.append(p)
    return out


def skellam_proxy(up_per_minute: float, down_per_minute: float,
                  horizon: int) -> tuple[float, float, float]:
    """P(N+ > N-), P(N+ < N-), P(equal); N+/- independent Poisson.

    Inputs are observed minute-bar directions, not actual quote/tick events.
    """
    if horizon not in HORIZONS or min(up_per_minute, down_per_minute) < 0:
        raise ValueError("invalid proxy intensity or horizon")
    plus = _pmf(up_per_minute * horizon)
    minus = _pmf(down_per_minute * horizon)
    up = down = flat = 0.0
    for a, pa in enumerate(plus):
        for b, pb in enumerate(minus):
            term = pa * pb
            if a > b:
                up += term
            elif a < b:
                down += term
            else:
                flat += term
    total = up + down + flat
    return (up / total, down / total, flat / total)


def _predict_at(series: list[tuple[datetime, float]], i: int,
                *, horizon: int, lag: int, window: int) -> ProbabilityForecast:
    """Compute probabilities from <=i only, including labels resolved <=i."""
    closes = [p for _, p in series[:i + 1]]
    minute_signs = [0] + [
        _sign(closes[k] - closes[k - 1]) for k in range(1, len(closes))
    ]
    start = max(lag, i - window)
    count = [1., 1., 1.]  # Laplace smoothing for unconditional benchmark
    matching = [0, 0, 0]
    n = n_matching = 0
    state = tuple(minute_signs[i - lag + 1:i + 1])
    for j in range(start, i - horizon + 1):
        target = _sign(closes[j + horizon] - closes[j])
        count[_index(target)] += 1.
        n += 1
        if tuple(minute_signs[j - lag + 1:j + 1]) == state:
            matching[_index(target)] += 1
            n_matching += 1
    if n < 24:
        raise ValueError("insufficient resolved historical labels")
    baseline = tuple(c / (n + 3) for c in count)
    shrink = 12.
    markov = tuple(
        (matching[k] + shrink * baseline[k]) / (n_matching + shrink)
        for k in range(3)
    )
    sample = minute_signs[max(1, i - window + 1):i + 1]
    plus = sum(x > 0 for x in sample) / len(sample)
    minus = sum(x < 0 for x in sample) / len(sample)
    poisson = skellam_proxy(plus, minus, horizon)
    target = series[i + horizon] if i + horizon < len(series) else None
    actual = _label(_sign(target[1] - closes[i])) if target else None
    ret = 100 * (target[1] / closes[i] - 1) if target else None
    return ProbabilityForecast(
        asof=series[i][0].isoformat(),
        target=target[0].isoformat() if target else None,
        horizon=horizon,
        baseline=baseline,
        markov=markov,
        skellam=poisson,
        actual=actual,
        return_pct=ret,
        sample_size=n,
        state_matches=n_matching,
    )


def walk_forward_probability(
    bars: Sequence, *, horizon: int = 1, lag: int = 2, window: int = 180
) -> tuple[list[ProbabilityForecast], ProbabilityForecast | None, int]:
    """Returns resolved out-of-sample forecasts, last as-of preview, gap count.

    Fit is freshly recomputed at every forecast as-of; never inspect unseen
    target closes. Preview is explicitly unlabeled and never used in metrics.
    """
    if horizon not in HORIZONS or lag not in (1, 2, 3) or not 60 <= window <= 1440:
        raise ValueError("unsupported horizon, lag, or window")
    groups = _segments(bars)
    resolved: list[ProbabilityForecast] = []
    preview = None
    for group_index, group in enumerate(groups):
        if len(group) < max(lag + horizon + 26, 40):
            continue
        # First prediction requires 24+ resolved h-ahead training examples.
        first = max(35, lag + horizon + 24)
        for i in range(first, len(group)):
            item = _predict_at(group, i, horizon=horizon, lag=lag, window=window)
            if item.actual is not None:
                resolved.append(item)
            elif group_index == len(groups) - 1 and i == len(group) - 1:
                preview = item
    return resolved, preview, max(0, len(groups) - 1)


def score_forecasts(items: Sequence[ProbabilityForecast], model: str,
                    *, threshold: float = .55, roundtrip_bps: float = 0.
                    ) -> dict[str, float | int | None]:
    """Three-class Brier, NLL, accuracy and per-forecast hypothetical payoffs.

    Trade proxy is NOT a fill, equity curve or additive strategy P/L. In
    particular horizons >1 have overlapping forward-return observations.
    """
    if model not in ("baseline", "markov", "skellam"):
        raise ValueError("unknown probability model")
    if not .34 <= threshold <= 1 or not 0 <= roundtrip_bps <= 1000:
        raise ValueError("invalid research assumptions")
    measured = [x for x in items if x.actual in LABELS and x.return_pct is not None]
    if not measured:
        return {"n": 0, "brier": None, "log_loss": None, "accuracy": None,
                "signals": 0, "mean_signal_net_pct": None}
    brier = nll = hits = signals = net = 0.
    for row in measured:
        probs = getattr(row, model)
        actual_i = LABELS.index(row.actual)
        brier += sum((p - (1 if k == actual_i else 0)) ** 2
                     for k, p in enumerate(probs))
        nll -= log(max(1e-12, probs[actual_i]))
        hits += int(probs.index(max(probs)) == actual_i)
        direction = 1 if probs[0] >= threshold and probs[0] > probs[1] else (
            -1 if probs[1] >= threshold and probs[1] > probs[0] else 0
        )
        if direction:
            signals += 1
            net += direction * row.return_pct - roundtrip_bps / 100
    n = len(measured)
    return {"n": n, "brier": brier / n, "log_loss": nll / n,
            "accuracy": hits / n, "signals": int(signals),
            "mean_signal_net_pct": (net / signals if signals else None)}


def up_calibration(items: Sequence[ProbabilityForecast],
                   model: str) -> list[dict[str, float | int]]:
    """Observed up-rate by forecast-probability decile, including counts."""
    out = []
    for bucket in range(10):
        rows = [p for p in items if p.actual in LABELS
                and min(9, int(getattr(p, model)[0] * 10)) == bucket]
        if rows:
            out.append({"p_up_range_start": bucket / 10,
                        "forecast_up_mean": sum(getattr(p, model)[0] for p in rows) / len(rows),
                        "observed_up_rate": sum(p.actual == "up" for p in rows) / len(rows),
                        "n": len(rows)})
    return out
