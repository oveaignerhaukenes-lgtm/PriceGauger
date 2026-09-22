from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from autotrader_pnl_comparison_v2 import AutoManagerPnlComparisonV2


@dataclass(frozen=True, slots=True)
class RegimeReturnCellV3:
    bucket: int
    strategy_key: str
    started_at: datetime
    ended_at: datetime
    return_pct: float


def _bucket_index(length: int, index: int, bucket_count: int) -> int:
    if length <= 1:
        return 0
    return min(bucket_count - 1, int(index * bucket_count / length))


def build_regime_return_cells_v3(
    comparison: AutoManagerPnlComparisonV2,
    *,
    bucket_count: int = 12,
) -> tuple[RegimeReturnCellV3, ...]:
    """Rebase every strategy inside each time bucket.

    Each bar answers only: how much did this strategy gain or lose *during this
    bucket*? Prior drawdown/cumulative equity is deliberately excluded. This makes
    regime changes visually comparable around a shared zero baseline.
    """
    if bucket_count < 1:
        raise ValueError("bucket_count must be positive")
    cells: list[RegimeReturnCellV3] = []
    for series in comparison.paper_series:
        points = tuple(series.points)
        if len(points) < 2:
            continue
        groups: dict[int, list] = {}
        for index, point in enumerate(points):
            groups.setdefault(_bucket_index(len(points), index, bucket_count), []).append(point)
        previous = points[0]
        for bucket in sorted(groups):
            group = groups[bucket]
            end = group[-1]
            start_equity = float(previous.equity)
            if start_equity <= 0:
                previous = end
                continue
            cells.append(
                RegimeReturnCellV3(
                    bucket=bucket,
                    strategy_key=series.strategy_key,
                    started_at=previous.closed_at,
                    ended_at=end.closed_at,
                    return_pct=((float(end.equity) / start_equity) - 1.0) * 100.0,
                )
            )
            previous = end
    return tuple(cells)


def latest_strategy_returns_v3(cells: Iterable[RegimeReturnCellV3]) -> dict[str, float]:
    latest: dict[str, RegimeReturnCellV3] = {}
    for cell in cells:
        current = latest.get(cell.strategy_key)
        if current is None or cell.ended_at > current.ended_at:
            latest[cell.strategy_key] = cell
    return {key: value.return_pct for key, value in latest.items()}


__all__ = ["RegimeReturnCellV3", "RelativeReturnPointV3", "build_regime_return_cells_v3", "build_relative_return_lines_v3", "latest_strategy_returns_v3"]


@dataclass(frozen=True, slots=True)
class RelativeReturnPointV3:
    strategy_key: str
    closed_at: datetime
    return_pct: float


def build_relative_return_lines_v3(
    comparison: AutoManagerPnlComparisonV2,
) -> tuple[RelativeReturnPointV3, ...]:
    """Continuous strategy lines rebased to zero at each strategy's visible start."""
    result: list[RelativeReturnPointV3] = []
    for series in comparison.paper_series:
        points = tuple(series.points)
        if not points:
            continue
        baseline = float(points[0].equity)
        if baseline <= 0:
            continue
        for point in points:
            result.append(
                RelativeReturnPointV3(
                    strategy_key=series.strategy_key,
                    closed_at=point.closed_at,
                    return_pct=((float(point.equity) / baseline) - 1.0) * 100.0,
                )
            )
    return tuple(result)
