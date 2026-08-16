from __future__ import annotations

from dataclasses import asdict, dataclass
from statistics import fmean
from typing import Any, Iterable

from database import connect
from parallel_forecast_evaluation_v2 import TECH_CONTEXT, TECH_ONLY


@dataclass(frozen=True, slots=True)
class BenchmarkAggregateV2:
    market: str
    horizon_seconds: int
    sample_size: int
    technical_mae: float
    technical_context_mae: float
    mae_delta: float
    technical_direction_hit_rate: float
    technical_context_direction_hit_rate: float
    direction_hit_rate_delta: float
    technical_interval_hit_rate: float
    technical_context_interval_hit_rate: float
    interval_hit_rate_delta: float
    context_wins: int
    ties: int
    context_losses: int

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class _PairedScoreV2:
    market: str
    horizon_seconds: int
    technical_absolute_error: float
    context_absolute_error: float
    technical_direction_hit: bool
    context_direction_hit: bool
    technical_interval_hit: bool
    context_interval_hit: bool


def _row_value(row, key: str, index: int):
    try:
        return row[key]
    except (TypeError, KeyError, IndexError):
        return row[index]


def load_paired_scores_v2(
    *,
    db_path: str = "pricegauger.db",
    market: str | None = None,
    horizon_seconds: int | None = None,
) -> tuple[_PairedScoreV2, ...]:
    """Load only fully paired TECH_ONLY/TECH_CONTEXT resolved outcomes."""
    clauses: list[str] = []
    params: list[object] = []
    if market is not None:
        clauses.append("o.market = ?")
        params.append(str(market))
    if horizon_seconds is not None:
        if int(horizon_seconds) <= 0:
            raise ValueError("horizon_seconds must be positive")
        clauses.append("o.horizon_seconds = ?")
        params.append(int(horizon_seconds))
    where = " WHERE " + " AND ".join(clauses) if clauses else ""

    query = f"""
        SELECT
            o.outcome_key,
            o.market,
            o.horizon_seconds,
            tech.absolute_error AS technical_absolute_error,
            ctx.absolute_error AS context_absolute_error,
            tech.direction_hit AS technical_direction_hit,
            ctx.direction_hit AS context_direction_hit,
            tech.interval_hit AS technical_interval_hit,
            ctx.interval_hit AS context_interval_hit
        FROM pg_v2_parallel_forecast_outcomes o
        JOIN pg_v2_parallel_forecast_scores tech
          ON tech.outcome_key = o.outcome_key AND tech.candidate_kind = ?
        JOIN pg_v2_parallel_forecast_scores ctx
          ON ctx.outcome_key = o.outcome_key AND ctx.candidate_kind = ?
        {where}
        ORDER BY o.market ASC, o.horizon_seconds ASC, o.matured_at ASC
    """
    with connect(db_path) as db:
        rows = db.execute(query, (TECH_ONLY, TECH_CONTEXT, *params)).fetchall()

    result: list[_PairedScoreV2] = []
    for row in rows:
        result.append(
            _PairedScoreV2(
                market=str(_row_value(row, "market", 1)),
                horizon_seconds=int(_row_value(row, "horizon_seconds", 2)),
                technical_absolute_error=float(_row_value(row, "technical_absolute_error", 3)),
                context_absolute_error=float(_row_value(row, "context_absolute_error", 4)),
                technical_direction_hit=bool(_row_value(row, "technical_direction_hit", 5)),
                context_direction_hit=bool(_row_value(row, "context_direction_hit", 6)),
                technical_interval_hit=bool(_row_value(row, "technical_interval_hit", 7)),
                context_interval_hit=bool(_row_value(row, "context_interval_hit", 8)),
            )
        )
    return tuple(result)


def aggregate_paired_scores_v2(rows: Iterable[_PairedScoreV2]) -> tuple[BenchmarkAggregateV2, ...]:
    grouped: dict[tuple[str, int], list[_PairedScoreV2]] = {}
    for row in rows:
        grouped.setdefault((row.market, row.horizon_seconds), []).append(row)

    aggregates: list[BenchmarkAggregateV2] = []
    for (market, horizon), group in sorted(grouped.items()):
        technical_mae = fmean(item.technical_absolute_error for item in group)
        context_mae = fmean(item.context_absolute_error for item in group)
        technical_direction = fmean(float(item.technical_direction_hit) for item in group)
        context_direction = fmean(float(item.context_direction_hit) for item in group)
        technical_interval = fmean(float(item.technical_interval_hit) for item in group)
        context_interval = fmean(float(item.context_interval_hit) for item in group)

        wins = ties = losses = 0
        for item in group:
            if item.context_absolute_error < item.technical_absolute_error:
                wins += 1
            elif item.context_absolute_error > item.technical_absolute_error:
                losses += 1
            else:
                ties += 1

        aggregates.append(
            BenchmarkAggregateV2(
                market=market,
                horizon_seconds=horizon,
                sample_size=len(group),
                technical_mae=technical_mae,
                technical_context_mae=context_mae,
                mae_delta=context_mae - technical_mae,
                technical_direction_hit_rate=technical_direction,
                technical_context_direction_hit_rate=context_direction,
                direction_hit_rate_delta=context_direction - technical_direction,
                technical_interval_hit_rate=technical_interval,
                technical_context_interval_hit_rate=context_interval,
                interval_hit_rate_delta=context_interval - technical_interval,
                context_wins=wins,
                ties=ties,
                context_losses=losses,
            )
        )
    return tuple(aggregates)


def load_benchmark_aggregates_v2(
    *,
    db_path: str = "pricegauger.db",
    market: str | None = None,
    horizon_seconds: int | None = None,
) -> tuple[BenchmarkAggregateV2, ...]:
    return aggregate_paired_scores_v2(
        load_paired_scores_v2(
            db_path=db_path,
            market=market,
            horizon_seconds=horizon_seconds,
        )
    )
