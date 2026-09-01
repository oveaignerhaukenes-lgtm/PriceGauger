from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

from autotrader_shadow_benchmark_exact_anchor_v2 import (
    load_shadow_benchmark_series_exact_anchor_v2,
)
from autotrader_shadow_benchmark_v2 import ShadowBenchmarkSeriesV2
from autotrader_strategy_catalog_v2 import (
    MACD_FLIP_STRATEGY_V2,
    MACD_LONG_FLAT_STRATEGY_V2,
    MACD_SHORT_FLAT_STRATEGY_V2,
)
from autotrader_strategy_enrollment_v2 import (
    EXECUTION_MODE_LIVE,
    StrategyEnrollmentV2,
)
from database import connect


# These are the strategies for which the current paper renderer has a truthful
# closed-30m replay. Intrabar LIVE is deliberately not mislabeled as a closed-30m
# paper curve; its realized LIVE ledger can still be compared against this control set.
PAPER_BENCHMARK_STRATEGY_KEYS_V2 = (
    MACD_LONG_FLAT_STRATEGY_V2,
    MACD_SHORT_FLAT_STRATEGY_V2,
    MACD_FLIP_STRATEGY_V2,
)


@dataclass(frozen=True, slots=True)
class LiveRealizedPnlEventV2:
    occurred_at: datetime
    realized_net_pnl: float


@dataclass(frozen=True, slots=True)
class LiveRealizedPnlPointV2:
    occurred_at: datetime
    cumulative_pnl: float
    return_pct: float


@dataclass(frozen=True, slots=True)
class AutoManagerPnlComparisonV2:
    pilot_key: str
    currency: str
    seed_equity: float
    started_at: datetime
    as_of: datetime
    live_realized: tuple[LiveRealizedPnlPointV2, ...]
    paper_series: tuple[ShadowBenchmarkSeriesV2, ...]


def _utc(value: Any) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def build_live_realized_pnl_curve_v2(
    *,
    seed_equity: float,
    started_at: datetime,
    as_of: datetime,
    events: Iterable[LiveRealizedPnlEventV2],
) -> tuple[LiveRealizedPnlPointV2, ...]:
    """Build a settled-only LIVE curve without estimating open-position P/L."""
    seed = float(seed_equity)
    if seed <= 0:
        raise ValueError("seed_equity must be positive")
    started = _utc(started_at)
    end = _utc(as_of)
    if end < started:
        raise ValueError("comparison end precedes start")

    cumulative = 0.0
    points = [LiveRealizedPnlPointV2(started, 0.0, 0.0)]
    for event in sorted(events, key=lambda item: _utc(item.occurred_at)):
        occurred = _utc(event.occurred_at)
        if occurred < started or occurred > end:
            continue
        cumulative += float(event.realized_net_pnl)
        points.append(
            LiveRealizedPnlPointV2(
                occurred_at=occurred,
                cumulative_pnl=cumulative,
                return_pct=(cumulative / seed) * 100.0,
            )
        )
    if points[-1].occurred_at < end:
        points.append(
            LiveRealizedPnlPointV2(
                occurred_at=end,
                cumulative_pnl=cumulative,
                return_pct=(cumulative / seed) * 100.0,
            )
        )
    return tuple(points)


def _load_live_realized_events_v2(pilot_key: str) -> tuple[LiveRealizedPnlEventV2, ...]:
    with connect() as db:
        rows = db.execute(
            """
            SELECT realized_net_pnl, created_at
            FROM pg_v2_autotrader_pilot_equity_events
            WHERE pilot_key = ?
            ORDER BY created_at ASC, event_id ASC
            """,
            (str(pilot_key),),
        ).fetchall()
    events = []
    for row in rows:
        values = dict(row) if isinstance(row, dict) else {
            "realized_net_pnl": row[0],
            "created_at": row[1],
        }
        events.append(
            LiveRealizedPnlEventV2(
                occurred_at=_utc(values["created_at"]),
                realized_net_pnl=float(values["realized_net_pnl"]),
            )
        )
    return tuple(events)


def load_automanager_pnl_comparison_v2(
    enrollments: Iterable[StrategyEnrollmentV2],
    *,
    db_path: str = "pricegauger.db",
    now: datetime | None = None,
) -> AutoManagerPnlComparisonV2:
    """Load truthful LIVE settled P/L beside canonical closed-30m paper controls.

    The LIVE controller may use a different signal clock (for example the intrabar
    1m-sampled 30m MACD). Paper series emitted here remain only the strategies for
    which the renderer has a truthful closed-30m replay; we never masquerade the
    intrabar policy as a bar-close policy merely to draw a line.
    """
    items = tuple(enrollments)
    live_items = tuple(item for item in items if item.execution_mode == EXECUTION_MODE_LIVE)
    if len(live_items) != 1:
        raise ValueError("P/L comparison requires exactly one LIVE controller")
    live = live_items[0]
    end = _utc(now or datetime.now(timezone.utc))
    paper = load_shadow_benchmark_series_exact_anchor_v2(
        items,
        strategy_keys=PAPER_BENCHMARK_STRATEGY_KEYS_V2,
        db_path=db_path,
        now=end,
    )
    if not paper:
        raise ValueError("P/L comparison has no canonical paper series")
    seed = float(paper[0].seed_equity)
    started = paper[0].started_at
    events = _load_live_realized_events_v2(live.pilot_key)
    actual = build_live_realized_pnl_curve_v2(
        seed_equity=seed,
        started_at=started,
        as_of=end,
        events=events,
    )
    return AutoManagerPnlComparisonV2(
        pilot_key=live.pilot_key,
        currency=paper[0].currency,
        seed_equity=seed,
        started_at=started,
        as_of=end,
        live_realized=actual,
        paper_series=paper,
    )


__all__ = [
    "AutoManagerPnlComparisonV2",
    "LiveRealizedPnlEventV2",
    "LiveRealizedPnlPointV2",
    "PAPER_BENCHMARK_STRATEGY_KEYS_V2",
    "build_live_realized_pnl_curve_v2",
    "load_automanager_pnl_comparison_v2",
]
