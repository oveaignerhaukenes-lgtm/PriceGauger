from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

from autotrader_cocktail_mode_1_shadow_v2 import load_cocktail_shadow_series_v1
from autotrader_shadow_benchmark_exact_anchor_v2 import (
    load_shadow_benchmark_series_exact_anchor_v2,
)
from autotrader_shadow_benchmark_v2 import ShadowBenchmarkSeriesV2
from autotrader_strategy_catalog_v2 import PAPER_30M_STRATEGIES_V2
from autotrader_strategy_enrollment_v2 import (
    EXECUTION_MODE_LIVE,
    StrategyEnrollmentV2,
    load_strategy_enrollment_v2,
)
from autotrader_strong_cocktail_shadow_v2 import load_strong_cocktail_comparison_series_v1
from database import connect


@dataclass(frozen=True, slots=True)
class LiveRealizedPnlEventV2:
    occurred_at: datetime
    realized_net_pnl: float
    pilot_key: str = ""
    strategy_key: str = ""


@dataclass(frozen=True, slots=True)
class LiveRealizedPnlPointV2:
    occurred_at: datetime
    cumulative_pnl: float
    return_pct: float
    pilot_key: str = ""
    strategy_key: str = ""


@dataclass(frozen=True, slots=True)
class LiveStrategyEpochV2:
    pilot_key: str
    strategy_key: str
    started_at: datetime
    ended_at: datetime | None


@dataclass(frozen=True, slots=True)
class _ProductLivePilotV2:
    enrollment: StrategyEnrollmentV2
    enrolled_at: datetime


@dataclass(frozen=True, slots=True)
class AutoManagerPnlComparisonV2:
    pilot_key: str
    product_key: str
    currency: str
    seed_equity: float
    started_at: datetime
    as_of: datetime
    live_realized: tuple[LiveRealizedPnlPointV2, ...]
    live_epochs: tuple[LiveStrategyEpochV2, ...]
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
    initial_pilot_key: str = "",
    initial_strategy_key: str = "",
    as_of_pilot_key: str = "",
    as_of_strategy_key: str = "",
) -> tuple[LiveRealizedPnlPointV2, ...]:
    """Build one settled-only LIVE curve across consecutive strategy cohorts.

    Strategy pilots keep separate ledgers for execution attribution. Reporting sums
    their realized events in chronological order so switching strategy never erases
    product history. Open/unrealized P/L is still deliberately excluded.
    """
    seed = float(seed_equity)
    if seed <= 0:
        raise ValueError("seed_equity must be positive")
    started = _utc(started_at)
    end = _utc(as_of)
    if end < started:
        raise ValueError("comparison end precedes start")

    cumulative = 0.0
    points = [
        LiveRealizedPnlPointV2(
            occurred_at=started,
            cumulative_pnl=0.0,
            return_pct=0.0,
            pilot_key=str(initial_pilot_key),
            strategy_key=str(initial_strategy_key),
        )
    ]
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
                pilot_key=str(event.pilot_key),
                strategy_key=str(event.strategy_key),
            )
        )
    if points[-1].occurred_at < end:
        points.append(
            LiveRealizedPnlPointV2(
                occurred_at=end,
                cumulative_pnl=cumulative,
                return_pct=(cumulative / seed) * 100.0,
                pilot_key=str(as_of_pilot_key or points[-1].pilot_key),
                strategy_key=str(as_of_strategy_key or points[-1].strategy_key),
            )
        )
    return tuple(points)


def _load_product_live_history_v2(live: StrategyEnrollmentV2) -> tuple[_ProductLivePilotV2, ...]:
    """Load every persisted LIVE cohort for one exact product, oldest first."""
    with connect() as db:
        rows = db.execute(
            """
            SELECT pilot_key, enrolled_at
            FROM pg_v2_autotrader_strategy_enrollments
            WHERE execution_mode = ?
              AND account_id = ?
              AND uic = ?
              AND asset_type = ?
              AND instrument_id = ?
            ORDER BY enrolled_at ASC, pilot_key ASC
            """,
            (
                EXECUTION_MODE_LIVE,
                live.account_id,
                int(live.uic),
                live.asset_type,
                int(live.instrument_id),
            ),
        ).fetchall()

    history: list[_ProductLivePilotV2] = []
    for row in rows:
        values = dict(row) if isinstance(row, dict) else {
            "pilot_key": row[0],
            "enrolled_at": row[1],
        }
        enrollment = load_strategy_enrollment_v2(str(values["pilot_key"]))
        if enrollment is None or enrollment.execution_mode != EXECUTION_MODE_LIVE:
            continue
        history.append(
            _ProductLivePilotV2(
                enrollment=enrollment,
                enrolled_at=_utc(values["enrolled_at"]),
            )
        )
    if not history:
        raise ValueError("P/L comparison has no persisted LIVE history for product")
    if all(item.enrollment.pilot_key != live.pilot_key for item in history):
        raise ValueError("active LIVE controller is missing from product P/L history")
    return tuple(history)


def _live_strategy_epochs_v2(
    history: tuple[_ProductLivePilotV2, ...],
) -> tuple[LiveStrategyEpochV2, ...]:
    epochs: list[LiveStrategyEpochV2] = []
    for index, item in enumerate(history):
        ended_at = history[index + 1].enrolled_at if index + 1 < len(history) else None
        epochs.append(
            LiveStrategyEpochV2(
                pilot_key=item.enrollment.pilot_key,
                strategy_key=item.enrollment.strategy_key,
                started_at=item.enrolled_at,
                ended_at=ended_at,
            )
        )
    return tuple(epochs)


def _load_live_realized_events_v2(
    history: tuple[_ProductLivePilotV2, ...],
) -> tuple[LiveRealizedPnlEventV2, ...]:
    pilot_to_strategy = {
        item.enrollment.pilot_key: item.enrollment.strategy_key
        for item in history
    }
    pilot_keys = tuple(pilot_to_strategy)
    if not pilot_keys:
        return ()
    placeholders = ", ".join("?" for _ in pilot_keys)
    with connect() as db:
        rows = db.execute(
            f"""
            SELECT pilot_key, realized_net_pnl, created_at
            FROM pg_v2_autotrader_pilot_equity_events
            WHERE pilot_key IN ({placeholders})
            ORDER BY created_at ASC, event_id ASC
            """,
            pilot_keys,
        ).fetchall()
    events = []
    for row in rows:
        values = dict(row) if isinstance(row, dict) else {
            "pilot_key": row[0],
            "realized_net_pnl": row[1],
            "created_at": row[2],
        }
        pilot_key = str(values["pilot_key"])
        events.append(
            LiveRealizedPnlEventV2(
                occurred_at=_utc(values["created_at"]),
                realized_net_pnl=float(values["realized_net_pnl"]),
                pilot_key=pilot_key,
                strategy_key=pilot_to_strategy.get(pilot_key, ""),
            )
        )
    return tuple(events)


def _cocktail_series_v2(
    *,
    instrument_id: int,
    seed_equity: float,
    currency: str,
    started_at: datetime,
    as_of: datetime,
) -> ShadowBenchmarkSeriesV2 | None:
    """Read adaptive shadow opportunistically; reporting must survive pre-schema rollout."""
    try:
        series = load_cocktail_shadow_series_v1(
            instrument_id=int(instrument_id),
            seed_equity=float(seed_equity),
            started_at=started_at,
            as_of=as_of,
        )
    except Exception:
        return None
    if series is None:
        return None
    return ShadowBenchmarkSeriesV2(
        strategy_key=series.strategy_key,
        execution_mode=series.execution_mode,
        currency=str(currency),
        seed_equity=series.seed_equity,
        started_at=series.started_at,
        points=series.points,
    )


def _strong_cocktail_series_v2(
    *,
    instrument_id: int,
    seed_equity: float,
    currency: str,
    started_at: datetime,
    as_of: datetime,
    db_path: str,
) -> tuple[ShadowBenchmarkSeriesV2, ...]:
    """Read Strong Cocktail + 1m control opportunistically from the same adaptive clock."""
    try:
        return load_strong_cocktail_comparison_series_v1(
            instrument_id=int(instrument_id),
            seed_equity=float(seed_equity),
            currency=str(currency),
            started_at=started_at,
            as_of=as_of,
            db_path=db_path,
        )
    except Exception:
        return ()


def load_automanager_pnl_comparison_v2(
    enrollments: Iterable[StrategyEnrollmentV2],
    *,
    db_path: str = "pricegauger.db",
    now: datetime | None = None,
) -> AutoManagerPnlComparisonV2:
    """Load durable product-history LIVE P/L beside canonical control models.

    Execution cohorts remain separate and auditable, but reporting is product-level:
    changing LIVE strategy must not reset or hide the realized Saxo history. Closed-30m
    controls replay from the oldest LIVE cohort's exact start anchor. Adaptive shadows
    are appended only from the moment their own canonical 1m data collection began.
    """
    items = tuple(enrollments)
    live_items = tuple(item for item in items if item.execution_mode == EXECUTION_MODE_LIVE)
    if len(live_items) != 1:
        raise ValueError("P/L comparison requires exactly one LIVE controller")
    live = live_items[0]
    end = _utc(now or datetime.now(timezone.utc))

    history = _load_product_live_history_v2(live)
    first = history[0]
    strategy_keys = tuple(item.key for item in PAPER_30M_STRATEGIES_V2)
    paper_controls = load_shadow_benchmark_series_exact_anchor_v2(
        (first.enrollment,),
        strategy_keys=strategy_keys,
        db_path=db_path,
        now=end,
    )
    if not paper_controls:
        raise ValueError("P/L comparison has no canonical paper series")

    seed = float(paper_controls[0].seed_equity)
    started = paper_controls[0].started_at
    currency = paper_controls[0].currency
    cocktail = _cocktail_series_v2(
        instrument_id=live.instrument_id,
        seed_equity=seed,
        currency=currency,
        started_at=started,
        as_of=end,
    )
    strong_controls = _strong_cocktail_series_v2(
        instrument_id=live.instrument_id,
        seed_equity=seed,
        currency=currency,
        started_at=started,
        as_of=end,
        db_path=db_path,
    )
    model_series = (
        tuple(paper_controls)
        + (() if cocktail is None else (cocktail,))
        + tuple(strong_controls)
    )

    events = _load_live_realized_events_v2(history)
    actual = build_live_realized_pnl_curve_v2(
        seed_equity=seed,
        started_at=started,
        as_of=end,
        events=events,
        initial_pilot_key=first.enrollment.pilot_key,
        initial_strategy_key=first.enrollment.strategy_key,
        as_of_pilot_key=live.pilot_key,
        as_of_strategy_key=live.strategy_key,
    )
    product_key = ":".join(
        (
            live.account_id,
            str(int(live.uic)),
            live.asset_type,
            str(int(live.instrument_id)),
        )
    )
    return AutoManagerPnlComparisonV2(
        pilot_key=live.pilot_key,
        product_key=product_key,
        currency=currency,
        seed_equity=seed,
        started_at=started,
        as_of=end,
        live_realized=actual,
        live_epochs=_live_strategy_epochs_v2(history),
        paper_series=model_series,
    )


__all__ = [
    "AutoManagerPnlComparisonV2",
    "LiveRealizedPnlEventV2",
    "LiveRealizedPnlPointV2",
    "LiveStrategyEpochV2",
    "build_live_realized_pnl_curve_v2",
    "load_automanager_pnl_comparison_v2",
]
