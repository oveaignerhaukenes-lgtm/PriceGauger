from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

from autotrader_shadow_benchmark_v2 import ShadowBenchmarkSeriesV2, ShadowEquityPointV2
from database import connect


@dataclass(frozen=True, slots=True)
class LiveLeveragePointV2:
    observed_at: datetime
    effective_leverage: float
    source: str


@dataclass(frozen=True, slots=True)
class LiveLeverageScheduleV2:
    points: tuple[LiveLeveragePointV2, ...]
    fallback_leverage: float
    source: str

    @property
    def representative_leverage(self) -> float:
        if self.points:
            return float(self.points[-1].effective_leverage)
        return float(self.fallback_leverage)


def _utc(value: Any) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def load_live_leverage_schedule_v2(
    *,
    pilot_key: str,
    account_id: str,
    uic: int,
    asset_type: str,
) -> LiveLeverageScheduleV2:
    """Load the effective leverage actually proven by Saxo OPEN prechecks.

    ``precheck_notional / budget_amount`` is the exact economic exposure ratio that
    AutoManager proposed for that entry, both expressed in account currency. The
    schedule is product-level, so strategy switches do not reset the comparison.

    If no accepted PG OPEN exists yet (for example a manually adopted starting
    position), fall back to the active pilot's configured max-effective-leverage.
    That fallback is deliberately explicit rather than silently reverting to 1x.
    """
    with connect() as db:
        rows = db.execute(
            """
            SELECT open.created_at, open.precheck_notional, open.budget_amount
            FROM pg_v2_autotrader_live_open_attempts AS open
            JOIN pg_v2_autotrader_execution_requests AS req
              ON req.request_id = open.request_id
            WHERE req.account_id = ? AND req.uic = ? AND req.asset_type = ?
              AND open.status IN ('ORDER_ACCEPTED', 'RECONCILED')
              AND open.precheck_notional > 0 AND open.budget_amount > 0
            ORDER BY open.created_at ASC
            """,
            (str(account_id), int(uic), str(asset_type)),
        ).fetchall()
        config = db.execute(
            """
            SELECT enabled, max_effective_leverage
            FROM pg_v2_autotrader_margin_configs
            WHERE pilot_key = ?
            """,
            (str(pilot_key),),
        ).fetchone()

    points: list[LiveLeveragePointV2] = []
    for row in rows:
        values = dict(row) if isinstance(row, dict) else {
            "created_at": row[0],
            "precheck_notional": row[1],
            "budget_amount": row[2],
        }
        budget = float(values["budget_amount"])
        notional = float(values["precheck_notional"])
        if budget <= 0 or notional <= 0:
            continue
        leverage = notional / budget
        if leverage <= 0:
            continue
        points.append(
            LiveLeveragePointV2(
                observed_at=_utc(values["created_at"]),
                effective_leverage=float(leverage),
                source="SAXO_OPEN_PRECHECK",
            )
        )

    fallback = 1.0
    source = "NO_LIVE_LEVERAGE_EVIDENCE"
    if config is not None:
        values = dict(config) if isinstance(config, dict) else {
            "enabled": config[0],
            "max_effective_leverage": config[1],
        }
        configured = float(values["max_effective_leverage"] or 0.0)
        if bool(values["enabled"]) and configured > 0:
            fallback = configured
            source = "PILOT_MARGIN_CONFIG"
    if points:
        # Before the first PG-created entry we use the first proven product ratio.
        # This keeps historical model curves on one economic scale without using a
        # different leverage simply because the starting position was manually adopted.
        fallback = float(points[0].effective_leverage)
        source = "FIRST_SAXO_OPEN_PRECHECK"
    return LiveLeverageScheduleV2(
        points=tuple(points),
        fallback_leverage=float(fallback),
        source=source,
    )


def leverage_at_v2(schedule: LiveLeverageScheduleV2, occurred_at: datetime) -> float:
    target = _utc(occurred_at)
    leverage = float(schedule.fallback_leverage)
    for point in schedule.points:
        if point.observed_at > target:
            break
        leverage = float(point.effective_leverage)
    return max(0.0, leverage)


def apply_live_equivalent_leverage_v2(
    series: ShadowBenchmarkSeriesV2,
    *,
    schedule: LiveLeverageScheduleV2,
) -> ShadowBenchmarkSeriesV2:
    """Map a 1x strategy equity path onto AutoManager's proven economic exposure.

    Signal timing and position state are unchanged. Only each already-observed strategy
    return is scaled by the product's effective leverage schedule. This makes the model
    Y-axis directly comparable with LIVE pilot-capital return while keeping the signal
    engines themselves independent of sizing.
    """
    if not series.points:
        return series
    seed = float(series.seed_equity)
    if seed <= 0:
        raise ValueError("shadow seed equity must be positive")

    leveraged_equity = seed
    transformed = [
        ShadowEquityPointV2(
            closed_at=series.points[0].closed_at,
            equity=leveraged_equity,
            position_state=series.points[0].position_state,
        )
    ]
    previous_unlevered = float(series.points[0].equity)
    for point in series.points[1:]:
        current_unlevered = float(point.equity)
        if previous_unlevered <= 0:
            raw_return = 0.0
        else:
            raw_return = (current_unlevered / previous_unlevered) - 1.0
        leverage = leverage_at_v2(schedule, point.closed_at)
        leveraged_equity = max(0.0, leveraged_equity * (1.0 + raw_return * leverage))
        transformed.append(
            ShadowEquityPointV2(
                closed_at=point.closed_at,
                equity=float(leveraged_equity),
                position_state=point.position_state,
            )
        )
        previous_unlevered = current_unlevered

    return ShadowBenchmarkSeriesV2(
        strategy_key=series.strategy_key,
        execution_mode=series.execution_mode,
        currency=series.currency,
        seed_equity=series.seed_equity,
        started_at=series.started_at,
        points=tuple(transformed),
    )


def apply_schedule_to_series_v2(
    series: Iterable[ShadowBenchmarkSeriesV2],
    *,
    schedule: LiveLeverageScheduleV2,
) -> tuple[ShadowBenchmarkSeriesV2, ...]:
    return tuple(apply_live_equivalent_leverage_v2(item, schedule=schedule) for item in series)


__all__ = [
    "LiveLeveragePointV2",
    "LiveLeverageScheduleV2",
    "apply_live_equivalent_leverage_v2",
    "apply_schedule_to_series_v2",
    "leverage_at_v2",
    "load_live_leverage_schedule_v2",
]
