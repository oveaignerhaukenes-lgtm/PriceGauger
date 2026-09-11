from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Mapping

import pandas as pd

from autotrader_hybrid_replay_v1 import BENCHMARK_NAMES_V1


REGIME_CHOPPY = "CHOPPY"
REGIME_EVEN = "EVEN"
REGIME_TREND = "TREND"
REGIME_IMPULSE = "IMPULSE"
REGIMES_V1 = (REGIME_CHOPPY, REGIME_EVEN, REGIME_TREND, REGIME_IMPULSE)
WINDOWS_V1: tuple[tuple[str, timedelta], ...] = (
    ("6h", timedelta(hours=6)),
    ("24h", timedelta(hours=24)),
    ("7d", timedelta(days=7)),
)


@dataclass(frozen=True, slots=True)
class RegimeSnapshotV1:
    label: str
    efficiency: float
    reversal_rate: float
    impulse_share: float
    net_move_pct: float
    observations: int


@dataclass(frozen=True, slots=True)
class StrategyWindowMetricV1:
    return_pct: float
    max_drawdown_pct: float
    switches: int


@dataclass(frozen=True, slots=True)
class StrategyScoreboardV1:
    windows: Mapping[str, RegimeSnapshotV1]
    metrics: Mapping[str, Mapping[str, StrategyWindowMetricV1]]
    regime_returns_7d: Mapping[str, Mapping[str, float]]


def _utc_now(value: datetime | None) -> pd.Timestamp:
    stamp = pd.Timestamp(value or datetime.now(timezone.utc))
    if stamp.tzinfo is None:
        return stamp.tz_localize("UTC")
    return stamp.tz_convert("UTC")


def classify_price_regime_v1(price: pd.Series) -> RegimeSnapshotV1:
    clean = pd.to_numeric(price, errors="coerce").dropna()
    if len(clean) < 4:
        return RegimeSnapshotV1(REGIME_EVEN, 0.0, 0.0, 0.0, 0.0, len(clean))

    delta = clean.diff().dropna()
    absolute = delta.abs()
    travel = float(absolute.sum())
    net = abs(float(clean.iloc[-1]) - float(clean.iloc[0]))
    efficiency = 0.0 if travel <= 0.0 else min(1.0, net / travel)

    signs = delta.where(delta != 0.0).dropna().map(lambda value: 1 if value > 0.0 else -1)
    if len(signs) < 2:
        reversal_rate = 0.0
    else:
        reversal_rate = float((signs != signs.shift(1)).iloc[1:].mean())

    if travel <= 0.0:
        impulse_share = 0.0
    else:
        top_count = min(3, len(absolute))
        impulse_share = float(absolute.nlargest(top_count).sum() / travel)

    start = float(clean.iloc[0])
    net_move_pct = 0.0 if start == 0.0 else ((float(clean.iloc[-1]) / start) - 1.0) * 100.0

    # IMPULSE is movement concentrated in very few bars. TREND is directional
    # efficiency. CHOPPY is low progress with many direction changes. Everything
    # between those states is intentionally called EVEN rather than overclassified.
    if len(clean) >= 12 and impulse_share >= 0.28:
        label = REGIME_IMPULSE
    elif efficiency >= 0.42 and reversal_rate <= 0.52:
        label = REGIME_TREND
    elif efficiency <= 0.16 and reversal_rate >= 0.52:
        label = REGIME_CHOPPY
    else:
        label = REGIME_EVEN

    return RegimeSnapshotV1(
        label=label,
        efficiency=float(efficiency),
        reversal_rate=float(reversal_rate),
        impulse_share=float(impulse_share),
        net_move_pct=float(net_move_pct),
        observations=len(clean),
    )


def _curve_window_metric_v1(curve: pd.Series, target: pd.Series, *, since: pd.Timestamp) -> StrategyWindowMetricV1:
    window = pd.to_numeric(curve[curve.index >= since], errors="coerce").dropna()
    if window.empty:
        return StrategyWindowMetricV1(0.0, 0.0, 0)

    equity = 1.0 + (window / 100.0)
    base = float(equity.iloc[0])
    end = float(equity.iloc[-1])
    return_pct = 0.0 if base <= 0.0 else ((end / base) - 1.0) * 100.0

    normalized = equity / base if base > 0.0 else equity
    peaks = normalized.cummax().replace(0.0, pd.NA)
    drawdown = ((normalized / peaks) - 1.0) * 100.0
    max_drawdown = float(drawdown.min()) if not drawdown.dropna().empty else 0.0

    target_window = pd.to_numeric(target[target.index >= since], errors="coerce").dropna()
    if target_window.empty:
        switches = 0
    else:
        switches = int((target_window != target_window.shift(1)).iloc[1:].sum())

    return StrategyWindowMetricV1(
        return_pct=float(return_pct),
        max_drawdown_pct=float(max_drawdown),
        switches=switches,
    )


def _hourly_regime_series_v1(price: pd.Series) -> pd.Series:
    labels = pd.Series(index=price.index, dtype="object")
    if price.empty:
        return labels
    for _, block in price.groupby(price.index.floor("60min")):
        if len(block) < 8:
            continue
        regime = classify_price_regime_v1(block)
        labels.loc[block.index] = regime.label
    return labels.ffill().bfill().fillna(REGIME_EVEN)


def _regime_returns_v1(replay: pd.DataFrame, *, since: pd.Timestamp) -> dict[str, dict[str, float]]:
    scoped = replay[replay.index >= since]
    if scoped.empty:
        return {name: {regime: 0.0 for regime in REGIMES_V1} for name in BENCHMARK_NAMES_V1}
    regimes = _hourly_regime_series_v1(scoped["PRICE"])
    result: dict[str, dict[str, float]] = {}
    for name in BENCHMARK_NAMES_V1:
        if name not in scoped.columns:
            continue
        equity = 1.0 + (pd.to_numeric(scoped[name], errors="coerce") / 100.0)
        minute_return = equity.pct_change().fillna(0.0)
        by_regime: dict[str, float] = {}
        for regime in REGIMES_V1:
            selected = minute_return[regimes == regime]
            if selected.empty:
                by_regime[regime] = 0.0
            else:
                by_regime[regime] = float(((1.0 + selected).prod() - 1.0) * 100.0)
        result[name] = by_regime
    return result


def build_strategy_scoreboard_v1(
    replay: pd.DataFrame,
    *,
    now: datetime | None = None,
) -> StrategyScoreboardV1:
    if "PRICE" not in replay.columns:
        raise ValueError("strategy scoreboard requires PRICE")
    if replay.empty:
        raise ValueError("strategy scoreboard requires replay rows")

    end = min(_utc_now(now), pd.Timestamp(replay.index.max()))
    windows: dict[str, RegimeSnapshotV1] = {}
    metrics: dict[str, dict[str, StrategyWindowMetricV1]] = {}

    for label, duration in WINDOWS_V1:
        since = end - duration
        windows[label] = classify_price_regime_v1(replay.loc[replay.index >= since, "PRICE"])

    for name in BENCHMARK_NAMES_V1:
        if name not in replay.columns:
            continue
        target_name = f"TARGET_{name}"
        if target_name not in replay.columns:
            continue
        metrics[name] = {}
        for label, duration in WINDOWS_V1:
            metrics[name][label] = _curve_window_metric_v1(
                replay[name], replay[target_name], since=end - duration
            )

    regime_returns = _regime_returns_v1(replay, since=end - timedelta(days=7))
    return StrategyScoreboardV1(
        windows=windows,
        metrics=metrics,
        regime_returns_7d=regime_returns,
    )


__all__ = [
    "REGIME_CHOPPY",
    "REGIME_EVEN",
    "REGIME_IMPULSE",
    "REGIME_TREND",
    "REGIMES_V1",
    "RegimeSnapshotV1",
    "StrategyScoreboardV1",
    "StrategyWindowMetricV1",
    "build_strategy_scoreboard_v1",
    "classify_price_regime_v1",
]
