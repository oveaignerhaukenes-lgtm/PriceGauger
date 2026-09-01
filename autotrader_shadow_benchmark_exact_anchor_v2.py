from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from autotrader_macd_dry_run_v2 import closed_30m_bars_v2, macd_observations_v2
from autotrader_pilot_equity_v2 import load_pilot_equity_v2
from autotrader_shadow_benchmark_v2 import (
    BENCHMARK_MAX_1M_BARS,
    BENCHMARK_WARMUP_DAYS,
    STATE_LONG,
    STATE_SHORT,
    ShadowBenchmarkSeriesV2,
    replay_shadow_benchmark_v2,
)
from autotrader_strategy_enrollment_v2 import EXECUTION_MODE_LIVE, StrategyEnrollmentV2
from canonical_market_bars_v2 import CanonicalMarketBarStoreV2
from database import connect


def _utc(value: Any) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _initial_state(direction: str) -> str:
    value = str(direction or "").strip().lower()
    if value == "buy":
        return STATE_LONG
    if value == "sell":
        return STATE_SHORT
    raise ValueError(f"unsupported managed-position direction: {direction}")


def _exact_anchor(
    enrollments: tuple[StrategyEnrollmentV2, ...],
) -> tuple[datetime, str, str]:
    """Resolve the cohort from persisted identity, never timestamp proximity.

    Strategy enrollment already persists ``anchor_net_position_id``.  The benchmark
    must use that exact observed Saxo position as its starting exposure.  A timestamp
    distance heuristic is neither necessary nor stable across re-enrollment/restart.
    """
    if not enrollments:
        raise ValueError("at least one strategy enrollment is required")
    first = enrollments[0]
    identity = (first.account_id, int(first.uic), first.asset_type, int(first.instrument_id))
    for item in enrollments[1:]:
        candidate = (item.account_id, int(item.uic), item.asset_type, int(item.instrument_id))
        if candidate != identity:
            raise ValueError("P/L comparison requires one exact product identity")

    anchors = tuple(dict.fromkeys(str(item.anchor_net_position_id) for item in enrollments))
    if len(anchors) != 1:
        raise ValueError("P/L comparison cohort does not share one exact starting-position anchor")
    anchor_id = anchors[0]

    pilot_keys = tuple(dict.fromkeys(str(item.pilot_key) for item in enrollments))
    placeholders = ", ".join("?" for _ in pilot_keys)
    with connect() as db:
        strategy_rows = db.execute(
            f"""
            SELECT enrolled_at
            FROM pg_v2_autotrader_strategy_enrollments
            WHERE pilot_key IN ({placeholders})
            ORDER BY enrolled_at ASC
            """,
            pilot_keys,
        ).fetchall()
        managed_row = db.execute(
            """
            SELECT net_position_id, direction, enrolled_at
            FROM pg_v2_autotrader_managed_positions
            WHERE account_id = ?
              AND net_position_id = ?
              AND uic = ?
              AND asset_type = ?
            LIMIT 1
            """,
            (first.account_id, anchor_id, int(first.uic), first.asset_type),
        ).fetchone()

    if not strategy_rows:
        raise ValueError("P/L comparison has no enrollment timestamp for supplied pilot cohort")
    if managed_row is None:
        raise ValueError(f"P/L comparison cannot resolve exact managed anchor {anchor_id}")

    started_at = min(_utc(dict(row)["enrolled_at"]) for row in strategy_rows)
    values = dict(managed_row) if isinstance(managed_row, dict) else {
        "net_position_id": managed_row[0],
        "direction": managed_row[1],
        "enrolled_at": managed_row[2],
    }
    return started_at, _initial_state(str(values["direction"])), str(values["net_position_id"])


def load_shadow_benchmark_series_exact_anchor_v2(
    enrollments: Iterable[StrategyEnrollmentV2],
    *,
    strategy_keys: Iterable[str],
    db_path: str = "pricegauger.db",
    now: datetime | None = None,
) -> tuple[ShadowBenchmarkSeriesV2, ...]:
    """Replay paper strategies from the exact persisted AutoManager start position."""
    items = tuple(enrollments)
    if not items:
        return ()
    started_at, initial_state, _ = _exact_anchor(items)
    end = _utc(now or datetime.now(timezone.utc))
    if end < started_at:
        raise ValueError("benchmark end precedes enrollment")

    first = items[0]
    canonical = CanonicalMarketBarStoreV2(db_path).load_instrument_range(
        instrument_id=int(first.instrument_id),
        start=started_at - timedelta(days=BENCHMARK_WARMUP_DAYS),
        end=end,
        limit=BENCHMARK_MAX_1M_BARS,
    )
    points = tuple(item.point for item in canonical)
    if not points:
        raise ValueError("P/L comparison has no exact canonical 1m history")
    closed = closed_30m_bars_v2(points, market=first.market_name)
    observations = macd_observations_v2(closed)
    if len(observations) < 2:
        raise ValueError("P/L comparison needs enough history for MACD 12/26/9")
    close_by_time = {_utc(bar.bar_time): float(bar.close) for bar in closed}

    live = next((item for item in items if item.execution_mode == EXECUTION_MODE_LIVE), None)
    if live is None:
        raise ValueError("P/L comparison requires one LIVE controller")
    ledger = load_pilot_equity_v2(pilot_key=live.pilot_key)
    by_strategy = {item.strategy_key: item for item in items}

    series: list[ShadowBenchmarkSeriesV2] = []
    for strategy_key in tuple(strategy_keys):
        replay = replay_shadow_benchmark_v2(
            strategy_key=str(strategy_key),
            seed_equity=ledger.seed_capital,
            initial_state=initial_state,
            started_at=started_at,
            observations=observations,
            close_by_time=close_by_time,
        )
        enrollment = by_strategy.get(str(strategy_key))
        series.append(
            ShadowBenchmarkSeriesV2(
                strategy_key=str(strategy_key),
                execution_mode=(enrollment.execution_mode if enrollment is not None else "SHADOW"),
                currency=ledger.currency,
                seed_equity=ledger.seed_capital,
                started_at=started_at,
                points=replay.equity_curve,
            )
        )
    return tuple(series)


__all__ = ["load_shadow_benchmark_series_exact_anchor_v2"]
