from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math
from typing import Any, Iterable

from autotrader_macd_dry_run_v2 import (
    SIGNAL_DOWN,
    SIGNAL_UP,
    MacdObservationV2,
    closed_30m_bars_v2,
    macd_observations_v2,
)
from autotrader_pilot_equity_v2 import load_pilot_equity_v2
from autotrader_strategy_catalog_v2 import (
    MACD_FLIP_STRATEGY_V2,
    MACD_LONG_FLAT_STRATEGY_V2,
    MACD_SHORT_FLAT_STRATEGY_V2,
)
from autotrader_strategy_enrollment_v2 import StrategyEnrollmentV2
from canonical_market_bars_v2 import CanonicalMarketBarStoreV2
from database import connect


STATE_FLAT = "FLAT"
STATE_LONG = "LONG"
STATE_SHORT = "SHORT"
SUPPORTED_STATES = {STATE_FLAT, STATE_LONG, STATE_SHORT}
SUPPORTED_STRATEGIES = {
    MACD_LONG_FLAT_STRATEGY_V2,
    MACD_SHORT_FLAT_STRATEGY_V2,
    MACD_FLIP_STRATEGY_V2,
}
BENCHMARK_WARMUP_DAYS = 10
BENCHMARK_MAX_1M_BARS = 100_000
ANCHOR_MAX_DISTANCE = timedelta(minutes=5)


@dataclass(frozen=True, slots=True)
class ProductBenchmarkAnchorV2:
    started_at: datetime
    initial_state: str
    managed_position_id: str


@dataclass(frozen=True, slots=True)
class ShadowEquityPointV2:
    closed_at: datetime
    equity: float
    position_state: str


@dataclass(frozen=True, slots=True)
class ShadowReplayResultV2:
    equity: float
    position_state: str
    transitions: int
    evaluated_bars: int
    first_bar_time: datetime | None
    last_bar_time: datetime | None
    equity_curve: tuple[ShadowEquityPointV2, ...]


@dataclass(frozen=True, slots=True)
class ShadowBenchmarkSnapshotV2:
    pilot_key: str
    strategy_key: str
    execution_mode: str
    currency: str
    seed_equity: float
    equity: float
    position_state: str
    transitions: int
    evaluated_bars: int
    started_at: datetime
    first_bar_time: datetime | None
    last_bar_time: datetime | None

    @property
    def return_pct(self) -> float:
        return ((self.equity / self.seed_equity) - 1.0) * 100.0

    @property
    def paper_pnl(self) -> float:
        return self.equity - self.seed_equity


@dataclass(frozen=True, slots=True)
class ShadowBenchmarkSeriesV2:
    strategy_key: str
    execution_mode: str
    currency: str
    seed_equity: float
    started_at: datetime
    points: tuple[ShadowEquityPointV2, ...]

    @property
    def return_pct(self) -> float:
        if not self.points:
            return 0.0
        return ((self.points[-1].equity / self.seed_equity) - 1.0) * 100.0


def _utc(value: Any) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _cross(previous: MacdObservationV2, current: MacdObservationV2) -> str | None:
    if previous.spread <= 0.0 < current.spread:
        return SIGNAL_UP
    if previous.spread >= 0.0 > current.spread:
        return SIGNAL_DOWN
    return None


def target_state_for_signal_v2(strategy_key: str, signal: str) -> str:
    if strategy_key not in SUPPORTED_STRATEGIES:
        raise ValueError(f"unsupported shadow strategy: {strategy_key}")
    if signal == SIGNAL_UP:
        if strategy_key == MACD_SHORT_FLAT_STRATEGY_V2:
            return STATE_FLAT
        return STATE_LONG
    if signal == SIGNAL_DOWN:
        if strategy_key == MACD_LONG_FLAT_STRATEGY_V2:
            return STATE_FLAT
        return STATE_SHORT
    raise ValueError(f"unsupported MACD signal: {signal}")


def apply_shadow_return_v2(*, equity: float, position_state: str, price_return: float) -> float:
    if position_state not in SUPPORTED_STATES:
        raise ValueError(f"unsupported shadow state: {position_state}")
    if not math.isfinite(float(equity)) or float(equity) < 0:
        raise ValueError("shadow equity must be finite and non-negative")
    if not math.isfinite(float(price_return)):
        raise ValueError("price_return must be finite")
    if position_state == STATE_FLAT:
        return float(equity)
    signed_return = float(price_return) if position_state == STATE_LONG else -float(price_return)
    return max(0.0, float(equity) * (1.0 + signed_return))


def replay_shadow_benchmark_v2(
    *,
    strategy_key: str,
    seed_equity: float,
    initial_state: str,
    started_at: datetime,
    observations: Iterable[MacdObservationV2],
    close_by_time: dict[datetime, float],
) -> ShadowReplayResultV2:
    """Replay strategy logic from one common post-enrollment closed-bar boundary.

    The observed starting exposure is authoritative. MACD regime before enrollment is
    never used to choose the initial paper position. The first fully closed 30m bar
    after enrollment establishes the common price baseline; any cross confirmed on
    that bar may change state at that close, but no pre-enrollment price return is
    attributed to the benchmark.
    """
    if strategy_key not in SUPPORTED_STRATEGIES:
        raise ValueError(f"unsupported shadow strategy: {strategy_key}")
    if initial_state not in SUPPORTED_STATES:
        raise ValueError(f"unsupported initial shadow state: {initial_state}")
    if not math.isfinite(float(seed_equity)) or float(seed_equity) <= 0:
        raise ValueError("seed_equity must be finite and positive")
    started = _utc(started_at)
    items = tuple(observations)
    if not items:
        return ShadowReplayResultV2(
            equity=float(seed_equity),
            position_state=initial_state,
            transitions=0,
            evaluated_bars=0,
            first_bar_time=None,
            last_bar_time=None,
            equity_curve=(),
        )

    first_index: int | None = None
    for index, item in enumerate(items):
        # bar_time is the 30m bucket start. It becomes actionable only at close.
        if _utc(item.bar_time) + timedelta(minutes=30) > started:
            first_index = index
            break
    if first_index is None:
        return ShadowReplayResultV2(
            equity=float(seed_equity),
            position_state=initial_state,
            transitions=0,
            evaluated_bars=0,
            first_bar_time=None,
            last_bar_time=None,
            equity_curve=(),
        )

    first = items[first_index]
    first_time = _utc(first.bar_time)
    first_close = close_by_time.get(first_time)
    if first_close is None or not math.isfinite(float(first_close)) or float(first_close) <= 0:
        raise ValueError("shadow benchmark first closed-bar price is unavailable")

    equity = float(seed_equity)
    state = initial_state
    transitions = 0
    evaluated = 1

    # A cross confirmed after enrollment is actionable even though the first bar is
    # used only as the common price baseline. This preserves signal timing while
    # deliberately excluding the unknown partial-bar return before enrollment.
    if first_index > 0:
        signal = _cross(items[first_index - 1], first)
        if signal is not None:
            next_state = target_state_for_signal_v2(strategy_key, signal)
            if next_state != state:
                transitions += 1
            state = next_state

    prior_close = float(first_close)
    last_time = first_time
    curve = [
        ShadowEquityPointV2(
            closed_at=first_time + timedelta(minutes=30),
            equity=equity,
            position_state=state,
        )
    ]
    for index in range(first_index + 1, len(items)):
        current = items[index]
        current_time = _utc(current.bar_time)
        close = close_by_time.get(current_time)
        if close is None or not math.isfinite(float(close)) or float(close) <= 0:
            raise ValueError("shadow benchmark closed-bar price is unavailable")
        price_return = (float(close) / prior_close) - 1.0
        equity = apply_shadow_return_v2(
            equity=equity,
            position_state=state,
            price_return=price_return,
        )

        next_state = STATE_FLAT if equity <= 0 else state
        signal = _cross(items[index - 1], current)
        if equity > 0 and signal is not None:
            next_state = target_state_for_signal_v2(strategy_key, signal)
        if next_state != state:
            transitions += 1
        state = next_state
        prior_close = float(close)
        last_time = current_time
        evaluated += 1
        curve.append(
            ShadowEquityPointV2(
                closed_at=current_time + timedelta(minutes=30),
                equity=equity,
                position_state=state,
            )
        )

    return ShadowReplayResultV2(
        equity=equity,
        position_state=state,
        transitions=transitions,
        evaluated_bars=evaluated,
        first_bar_time=first_time,
        last_bar_time=last_time,
        equity_curve=tuple(curve),
    )


def _initial_state_from_saxo_direction(direction: str) -> str:
    value = str(direction or "").strip().lower()
    if value == "buy":
        return STATE_LONG
    if value == "sell":
        return STATE_SHORT
    raise ValueError(f"unsupported managed-position direction: {direction}")


def _load_product_anchor_v2(enrollments: tuple[StrategyEnrollmentV2, ...]) -> ProductBenchmarkAnchorV2:
    if not enrollments:
        raise ValueError("at least one strategy enrollment is required")
    first = enrollments[0]
    identity = (first.account_id, int(first.uic), first.asset_type, int(first.instrument_id))
    for item in enrollments[1:]:
        candidate = (item.account_id, int(item.uic), item.asset_type, int(item.instrument_id))
        if candidate != identity:
            raise ValueError("shadow comparison requires one exact product identity")

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
        managed_rows = db.execute(
            """
            SELECT net_position_id, direction, enrolled_at
            FROM pg_v2_autotrader_managed_positions
            WHERE account_id = ? AND uic = ? AND asset_type = ?
            ORDER BY enrolled_at ASC
            """,
            (first.account_id, int(first.uic), first.asset_type),
        ).fetchall()

    if not strategy_rows:
        raise ValueError("shadow benchmark has no enrollment timestamp for supplied pilot cohort")
    started_at = min(_utc(dict(row)["enrolled_at"]) for row in strategy_rows)
    if not managed_rows:
        raise ValueError("shadow benchmark has no managed starting-position observation")

    candidates = []
    for row in managed_rows:
        values = dict(row)
        enrolled_at = _utc(values["enrolled_at"])
        candidates.append(
            (
                abs(enrolled_at - started_at),
                str(values["net_position_id"]),
                str(values["direction"]),
            )
        )
    distance, net_position_id, direction = min(candidates, key=lambda item: item[0])
    if distance > ANCHOR_MAX_DISTANCE:
        raise ValueError("managed starting-position observation is too far from strategy enrollment")
    return ProductBenchmarkAnchorV2(
        started_at=started_at,
        initial_state=_initial_state_from_saxo_direction(direction),
        managed_position_id=net_position_id,
    )


def load_shadow_benchmark_snapshots_v2(
    enrollments: Iterable[StrategyEnrollmentV2],
    *,
    db_path: str = "pricegauger.db",
    now: datetime | None = None,
) -> tuple[ShadowBenchmarkSnapshotV2, ...]:
    """Return apples-to-apples paper results for all strategies on one product.

    This is a deterministic read over canonical history, not an execution runtime.
    It never writes shadow P/L into the authoritative Saxo equity ledger and has no
    order authority. All supplied strategies share one observed starting exposure,
    one cohort start time and the same exact canonical 30m price path.
    """
    items = tuple(enrollments)
    if not items:
        return ()
    anchor = _load_product_anchor_v2(items)
    end = now or datetime.now(timezone.utc)
    end = _utc(end)
    if end < anchor.started_at:
        raise ValueError("benchmark end precedes enrollment")

    first = items[0]
    canonical = CanonicalMarketBarStoreV2(db_path).load_instrument_range(
        instrument_id=int(first.instrument_id),
        start=anchor.started_at - timedelta(days=BENCHMARK_WARMUP_DAYS),
        end=end,
        limit=BENCHMARK_MAX_1M_BARS,
    )
    points = tuple(item.point for item in canonical)
    if not points:
        raise ValueError("shadow benchmark has no exact canonical 1m history")
    closed = closed_30m_bars_v2(points, market=first.market_name)
    observations = macd_observations_v2(closed)
    if len(observations) < 2:
        raise ValueError("shadow benchmark needs enough history for MACD 12/26/9")
    close_by_time = {_utc(bar.bar_time): float(bar.close) for bar in closed}

    snapshots: list[ShadowBenchmarkSnapshotV2] = []
    for enrollment in items:
        if enrollment.strategy_key not in SUPPORTED_STRATEGIES:
            continue
        ledger = load_pilot_equity_v2(pilot_key=enrollment.pilot_key)
        replay = replay_shadow_benchmark_v2(
            strategy_key=enrollment.strategy_key,
            seed_equity=ledger.seed_capital,
            initial_state=anchor.initial_state,
            started_at=anchor.started_at,
            observations=observations,
            close_by_time=close_by_time,
        )
        snapshots.append(
            ShadowBenchmarkSnapshotV2(
                pilot_key=enrollment.pilot_key,
                strategy_key=enrollment.strategy_key,
                execution_mode=enrollment.execution_mode,
                currency=ledger.currency,
                seed_equity=ledger.seed_capital,
                equity=replay.equity,
                position_state=replay.position_state,
                transitions=replay.transitions,
                evaluated_bars=replay.evaluated_bars,
                started_at=anchor.started_at,
                first_bar_time=replay.first_bar_time,
                last_bar_time=replay.last_bar_time,
            )
        )
    return tuple(snapshots)


def load_shadow_benchmark_series_v2(
    enrollments: Iterable[StrategyEnrollmentV2],
    *,
    strategy_keys: Iterable[str] | None = None,
    db_path: str = "pricegauger.db",
    now: datetime | None = None,
) -> tuple[ShadowBenchmarkSeriesV2, ...]:
    """Return deterministic paper equity curves on one shared canonical basis.

    The supplied enrollments establish exact product identity, observed starting
    exposure and cohort start. ``strategy_keys`` may include supported strategies
    that were not enrolled as daemons; those curves are read-only retrospective
    policy replays and never gain execution or ledger authority.
    """
    items = tuple(enrollments)
    if not items:
        return ()
    anchor = _load_product_anchor_v2(items)
    end = _utc(now or datetime.now(timezone.utc))
    if end < anchor.started_at:
        raise ValueError("benchmark end precedes enrollment")

    first = items[0]
    canonical = CanonicalMarketBarStoreV2(db_path).load_instrument_range(
        instrument_id=int(first.instrument_id),
        start=anchor.started_at - timedelta(days=BENCHMARK_WARMUP_DAYS),
        end=end,
        limit=BENCHMARK_MAX_1M_BARS,
    )
    points = tuple(item.point for item in canonical)
    if not points:
        raise ValueError("shadow benchmark has no exact canonical 1m history")
    closed = closed_30m_bars_v2(points, market=first.market_name)
    observations = macd_observations_v2(closed)
    if len(observations) < 2:
        raise ValueError("shadow benchmark needs enough history for MACD 12/26/9")
    close_by_time = {_utc(bar.bar_time): float(bar.close) for bar in closed}

    by_strategy = {item.strategy_key: item for item in items}
    live = next((item for item in items if item.execution_mode == "LIVE_MANAGE"), items[0])
    ledger = load_pilot_equity_v2(pilot_key=live.pilot_key)
    requested = tuple(strategy_keys) if strategy_keys is not None else tuple(by_strategy)
    unsupported = set(requested) - SUPPORTED_STRATEGIES
    if unsupported:
        raise ValueError(f"unsupported shadow strategies: {sorted(unsupported)}")

    series: list[ShadowBenchmarkSeriesV2] = []
    for strategy_key in requested:
        replay = replay_shadow_benchmark_v2(
            strategy_key=strategy_key,
            seed_equity=ledger.seed_capital,
            initial_state=anchor.initial_state,
            started_at=anchor.started_at,
            observations=observations,
            close_by_time=close_by_time,
        )
        enrollment = by_strategy.get(strategy_key)
        series.append(
            ShadowBenchmarkSeriesV2(
                strategy_key=strategy_key,
                execution_mode=(enrollment.execution_mode if enrollment is not None else "SHADOW"),
                currency=ledger.currency,
                seed_equity=ledger.seed_capital,
                started_at=anchor.started_at,
                points=replay.equity_curve,
            )
        )
    return tuple(series)


__all__ = [
    "ProductBenchmarkAnchorV2",
    "ShadowBenchmarkSeriesV2",
    "ShadowBenchmarkSnapshotV2",
    "ShadowEquityPointV2",
    "ShadowReplayResultV2",
    "STATE_FLAT",
    "STATE_LONG",
    "STATE_SHORT",
    "apply_shadow_return_v2",
    "load_shadow_benchmark_snapshots_v2",
    "load_shadow_benchmark_series_v2",
    "replay_shadow_benchmark_v2",
    "target_state_for_signal_v2",
]
