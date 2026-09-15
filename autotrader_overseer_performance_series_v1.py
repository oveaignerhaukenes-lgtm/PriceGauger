from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime
from math import sqrt
from typing import Sequence

from autotrader_overseer_performance_v1 import (
    FLAT_MODEL_V1,
    ModelPerformanceV1,
    OVERSEER_PERFORMANCE_STRATEGY_KEY_V1,
    choose_performance_model_v1,
)
from autotrader_shadow_benchmark_v2 import ShadowBenchmarkSeriesV2, ShadowEquityPointV2


OVERSEER_PERFORMANCE_SERIES_VERSION_V1 = "OVERSEER-PERFORMANCE-60M-v1"
WINDOW_POINTS_V1 = 60
CHALLENGER_CONFIRMATIONS_V1 = 3


def _aligned_models(series: Sequence[ShadowBenchmarkSeriesV2]) -> tuple[ShadowBenchmarkSeriesV2, ...]:
    usable = tuple(item for item in series if item.points and item.strategy_key != OVERSEER_PERFORMANCE_STRATEGY_KEY_V1)
    if not usable:
        return ()
    clock = tuple(point.closed_at for point in usable[0].points)
    return tuple(item for item in usable if tuple(point.closed_at for point in item.points) == clock)


def _performance(item: ShadowBenchmarkSeriesV2, index: int, window: int) -> ModelPerformanceV1:
    start = max(0, index - window + 1)
    equities = [float(point.equity) for point in item.points[start:index + 1]]
    seed = equities[0] if equities else float(item.seed_equity)
    recent = 0.0 if seed <= 0 else ((equities[-1] / seed) - 1.0) * 100.0
    peak = equities[0]
    worst_dd = 0.0
    deltas: list[float] = []
    for left, right in zip(equities, equities[1:]):
        peak = max(peak, right)
        if peak > 0:
            worst_dd = min(worst_dd, ((right / peak) - 1.0) * 100.0)
        if left > 0:
            deltas.append(((right / left) - 1.0) * 100.0)
    positive = sum(1 for value in deltas if value > 0.0) / len(deltas) if deltas else 0.5
    if len(deltas) < 2:
        stability = 0.5
    else:
        mean = sum(deltas) / len(deltas)
        variance = sum((value - mean) ** 2 for value in deltas) / len(deltas)
        stability = 1.0 / (1.0 + sqrt(max(0.0, variance)))
    return ModelPerformanceV1(item.strategy_key, recent, worst_dd, positive, stability)


def load_overseer_performance_series_v1(
    model_series: Sequence[ShadowBenchmarkSeriesV2],
    *,
    window_points: int = WINDOW_POINTS_V1,
    challenger_confirmations: int = CHALLENGER_CONFIRMATIONS_V1,
) -> ShadowBenchmarkSeriesV2 | None:
    """Replay Overseer from past model performance only.

    Decision at point t uses model equity through t. The selected expert is then applied
    only to the next interval t->t+1, preventing future-return leakage.
    """
    models = _aligned_models(model_series)
    if not models:
        return None
    count = min(len(item.points) for item in models)
    if count < 2:
        return None
    seed = float(models[0].seed_equity)
    incumbent = FLAT_MODEL_V1
    challenger = FLAT_MODEL_V1
    challenger_count = 0
    equity = seed
    points = [ShadowEquityPointV2(models[0].points[0].closed_at, equity, "FLAT")]

    for index in range(count - 1):
        evidence = tuple(_performance(item, index, max(3, int(window_points))) for item in models)
        decision = choose_performance_model_v1(evidence, incumbent=incumbent)
        desired = decision.model
        if desired != incumbent:
            if desired == challenger:
                challenger_count += 1
            else:
                challenger = desired
                challenger_count = 1
            if challenger_count >= max(1, int(challenger_confirmations)):
                incumbent = desired
                challenger = FLAT_MODEL_V1
                challenger_count = 0
        else:
            challenger = FLAT_MODEL_V1
            challenger_count = 0

        position = "FLAT"
        if incumbent != FLAT_MODEL_V1:
            selected = next((item for item in models if item.strategy_key == incumbent), None)
            if selected is not None:
                left = float(selected.points[index].equity)
                right = float(selected.points[index + 1].equity)
                if left > 0:
                    equity *= right / left
                position = str(selected.points[index].position_state)
        points.append(ShadowEquityPointV2(models[0].points[index + 1].closed_at, equity, position))

    return ShadowBenchmarkSeriesV2(
        strategy_key=OVERSEER_PERFORMANCE_STRATEGY_KEY_V1,
        execution_mode="SHADOW_OVERSEER",
        currency=models[0].currency,
        seed_equity=seed,
        started_at=models[0].started_at,
        points=tuple(points),
    )


__all__ = [
    "CHALLENGER_CONFIRMATIONS_V1",
    "OVERSEER_PERFORMANCE_SERIES_VERSION_V1",
    "WINDOW_POINTS_V1",
    "load_overseer_performance_series_v1",
]
