from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
import time
from typing import Iterable
from uuid import NAMESPACE_URL, uuid5

import pandas as pd

from database import connect, using_postgres
from instrument_registry_v2 import list_subscribed_sources_v2
from market_history_store import MarketHistoryStore
from timeframe_contract_v2 import normalize_canonical_1m_v2
from trading_desk import ChartBar
from trading_desk_indicators import calculate_indicators


LOGGER = logging.getLogger("pricegauger.autotrader.macd_dry_run_v2")
STRATEGY_KEY = "macd-30m-long-flat-v1"
TIMEFRAME = "30m"
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
POSITION_FLAT = "FLAT"
POSITION_LONG = "LONG"
SIGNAL_UP = "CROSS_UP"
SIGNAL_DOWN = "CROSS_DOWN"
ACTION_BUY = "WOULD_BUY"
ACTION_SELL_ALL = "WOULD_SELL_ALL"
ACTION_HOLD = "HOLD"


@dataclass(frozen=True, slots=True)
class MacdObservationV2:
    bar_time: datetime
    macd: float
    signal: float

    @property
    def spread(self) -> float:
        return self.macd - self.signal


@dataclass(frozen=True, slots=True)
class DryRunStateV2:
    market_id: int
    market_name: str
    position_state: str = POSITION_FLAT
    last_evaluated_bar_time: datetime | None = None
    last_signal_bar_time: datetime | None = None


@dataclass(frozen=True, slots=True)
class DryRunTransitionV2:
    event_id: str
    market_id: int
    market_name: str
    signal_bar_time: datetime
    signal: str
    prior_state: str
    desired_state: str
    action: str
    previous_macd: float
    previous_signal: float
    current_macd: float
    current_signal: float


@dataclass(frozen=True, slots=True)
class DryRunCycleSummaryV2:
    attempted: int
    evaluated: int
    transitions: int
    failed: int


def _utc(value: datetime | str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def ensure_macd_dry_run_schema_v2() -> None:
    if not using_postgres():
        raise RuntimeError("MACD dry-run runtime requires PostgreSQL")
    with connect() as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS pg_v2_autotrader_strategy_state (
                strategy_key TEXT NOT NULL,
                market_id BIGINT NOT NULL REFERENCES pg_v2_markets(market_id),
                position_state TEXT NOT NULL CHECK (position_state IN ('FLAT', 'LONG')),
                last_evaluated_bar_time TIMESTAMPTZ,
                last_signal_bar_time TIMESTAMPTZ,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                PRIMARY KEY(strategy_key, market_id)
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS pg_v2_autotrader_strategy_events (
                event_id UUID PRIMARY KEY,
                strategy_key TEXT NOT NULL,
                market_id BIGINT NOT NULL REFERENCES pg_v2_markets(market_id),
                signal_bar_time TIMESTAMPTZ NOT NULL,
                signal TEXT NOT NULL CHECK (signal IN ('CROSS_UP', 'CROSS_DOWN')),
                prior_state TEXT NOT NULL CHECK (prior_state IN ('FLAT', 'LONG')),
                desired_state TEXT NOT NULL CHECK (desired_state IN ('FLAT', 'LONG')),
                action TEXT NOT NULL CHECK (action IN ('WOULD_BUY', 'WOULD_SELL_ALL', 'HOLD')),
                previous_macd DOUBLE PRECISION NOT NULL,
                previous_signal DOUBLE PRECISION NOT NULL,
                current_macd DOUBLE PRECISION NOT NULL,
                current_signal DOUBLE PRECISION NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE(strategy_key, market_id, signal_bar_time, signal)
            )
            """
        )


def closed_30m_bars_v2(
    points: Iterable[tuple[str, float]],
    *,
    market: str,
) -> tuple[ChartBar, ...]:
    """Build only fully closed UTC/epoch-aligned 30m bars from canonical 1m observations.

    The live Technical Core deliberately keeps a forming bucket. AutoTrader does not:
    a 30m bucket is eligible only after the final canonical minute of that bucket can
    have completed. Missing minutes are never forward-filled.
    """
    one = normalize_canonical_1m_v2(points)
    latest = one["timestamp"].iloc[-1]
    observed_through = latest.floor("min") + pd.Timedelta(minutes=1)
    aggregated = (
        one.set_index("timestamp")
        .resample("30min", label="left", closed="left", origin="epoch")
        .agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"))
        .dropna(subset=["close"])
    )
    if aggregated.empty:
        return ()
    aggregated = aggregated.loc[(aggregated.index + pd.Timedelta(minutes=30)) <= observed_through]
    bars: list[ChartBar] = []
    for stamp, row in aggregated.iterrows():
        bars.append(
            ChartBar(
                market=market,
                bar_time=stamp.to_pydatetime().astimezone(timezone.utc).isoformat(),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=None,
            )
        )
    return tuple(bars)


def macd_observations_v2(bars: tuple[ChartBar, ...]) -> tuple[MacdObservationV2, ...]:
    indicators = calculate_indicators(
        bars,
        macd_fast=MACD_FAST,
        macd_slow=MACD_SLOW,
        macd_signal=MACD_SIGNAL,
    )
    macd_by_time = {_utc(point.bar_time): point.value for point in indicators.macd}
    signal_by_time = {_utc(point.bar_time): point.value for point in indicators.macd_signal}
    return tuple(
        MacdObservationV2(bar_time=stamp, macd=float(macd_by_time[stamp]), signal=float(signal_by_time[stamp]))
        for stamp in sorted(set(macd_by_time).intersection(signal_by_time))
    )


def _cross(previous: MacdObservationV2, current: MacdObservationV2) -> str | None:
    if previous.spread <= 0.0 < current.spread:
        return SIGNAL_UP
    if previous.spread >= 0.0 > current.spread:
        return SIGNAL_DOWN
    return None


def _transition_for_signal(
    *,
    market_id: int,
    market_name: str,
    signal: str,
    previous: MacdObservationV2,
    current: MacdObservationV2,
    prior_state: str,
) -> DryRunTransitionV2:
    if signal == SIGNAL_UP:
        desired = POSITION_LONG
        action = ACTION_BUY if prior_state == POSITION_FLAT else ACTION_HOLD
    elif signal == SIGNAL_DOWN:
        desired = POSITION_FLAT
        action = ACTION_SELL_ALL if prior_state == POSITION_LONG else ACTION_HOLD
    else:  # pragma: no cover - internal contract guard
        raise ValueError(f"unsupported signal: {signal}")
    identity = f"{STRATEGY_KEY}|{market_id}|{current.bar_time.isoformat()}|{signal}"
    return DryRunTransitionV2(
        event_id=str(uuid5(NAMESPACE_URL, identity)),
        market_id=int(market_id),
        market_name=market_name,
        signal_bar_time=current.bar_time,
        signal=signal,
        prior_state=prior_state,
        desired_state=desired,
        action=action,
        previous_macd=previous.macd,
        previous_signal=previous.signal,
        current_macd=current.macd,
        current_signal=current.signal,
    )


def _row_value(row, key: str, index: int):
    if isinstance(row, dict):
        return row[key]
    try:
        return row[key]
    except (TypeError, IndexError):
        return row[index]


def load_dry_run_state_v2(*, market_id: int, market_name: str) -> DryRunStateV2:
    with connect() as db:
        row = db.execute(
            """
            SELECT position_state, last_evaluated_bar_time, last_signal_bar_time
            FROM pg_v2_autotrader_strategy_state
            WHERE strategy_key = ? AND market_id = ?
            """,
            (STRATEGY_KEY, int(market_id)),
        ).fetchone()
    if row is None:
        return DryRunStateV2(market_id=int(market_id), market_name=market_name)
    last_evaluated = _row_value(row, "last_evaluated_bar_time", 1)
    last_signal = _row_value(row, "last_signal_bar_time", 2)
    return DryRunStateV2(
        market_id=int(market_id),
        market_name=market_name,
        position_state=str(_row_value(row, "position_state", 0)),
        last_evaluated_bar_time=_utc(last_evaluated) if last_evaluated else None,
        last_signal_bar_time=_utc(last_signal) if last_signal else None,
    )


def _persist_progress_v2(
    *,
    state: DryRunStateV2,
    last_evaluated_bar_time: datetime,
    transition: DryRunTransitionV2 | None,
) -> DryRunStateV2:
    desired_state = state.position_state if transition is None else transition.desired_state
    last_signal = state.last_signal_bar_time if transition is None else transition.signal_bar_time
    with connect() as db:
        if transition is not None:
            db.execute(
                """
                INSERT INTO pg_v2_autotrader_strategy_events
                    (event_id, strategy_key, market_id, signal_bar_time, signal,
                     prior_state, desired_state, action,
                     previous_macd, previous_signal, current_macd, current_signal)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (event_id) DO NOTHING
                """,
                (
                    transition.event_id,
                    STRATEGY_KEY,
                    transition.market_id,
                    transition.signal_bar_time,
                    transition.signal,
                    transition.prior_state,
                    transition.desired_state,
                    transition.action,
                    transition.previous_macd,
                    transition.previous_signal,
                    transition.current_macd,
                    transition.current_signal,
                ),
            )
        db.execute(
            """
            INSERT INTO pg_v2_autotrader_strategy_state
                (strategy_key, market_id, position_state, last_evaluated_bar_time,
                 last_signal_bar_time, updated_at)
            VALUES (?, ?, ?, ?, ?, now())
            ON CONFLICT (strategy_key, market_id) DO UPDATE SET
                position_state = EXCLUDED.position_state,
                last_evaluated_bar_time = EXCLUDED.last_evaluated_bar_time,
                last_signal_bar_time = EXCLUDED.last_signal_bar_time,
                updated_at = now()
            """,
            (
                STRATEGY_KEY,
                state.market_id,
                desired_state,
                last_evaluated_bar_time,
                last_signal,
            ),
        )
    return DryRunStateV2(
        market_id=state.market_id,
        market_name=state.market_name,
        position_state=desired_state,
        last_evaluated_bar_time=last_evaluated_bar_time,
        last_signal_bar_time=last_signal,
    )


def evaluate_macd_long_flat_points_v2(
    *,
    market_id: int,
    market_name: str,
    points: Iterable[tuple[str, float]],
) -> tuple[DryRunStateV2, tuple[DryRunTransitionV2, ...]]:
    bars = closed_30m_bars_v2(points, market=market_name)
    observations = macd_observations_v2(bars)
    if len(observations) < 2:
        raise ValueError("MACD dry-run requires enough closed 30m bars for MACD 12/26/9")

    state = load_dry_run_state_v2(market_id=market_id, market_name=market_name)
    transitions: list[DryRunTransitionV2] = []
    for previous, current in zip(observations, observations[1:]):
        if state.last_evaluated_bar_time is not None and current.bar_time <= state.last_evaluated_bar_time:
            continue
        signal = _cross(previous, current)
        transition = None
        if signal is not None:
            transition = _transition_for_signal(
                market_id=market_id,
                market_name=market_name,
                signal=signal,
                previous=previous,
                current=current,
                prior_state=state.position_state,
            )
            transitions.append(transition)
        state = _persist_progress_v2(
            state=state,
            last_evaluated_bar_time=current.bar_time,
            transition=transition,
        )
    return state, tuple(transitions)


def evaluate_market_macd_dry_run_v2(
    *,
    market_id: int,
    market_name: str,
    history_store: MarketHistoryStore,
    now: datetime | None = None,
) -> tuple[DryRunStateV2, tuple[DryRunTransitionV2, ...]]:
    end = _utc(now or datetime.now(timezone.utc))
    start = end - timedelta(days=14)
    points = history_store.load_range(market=market_name, start=start, end=end, limit=50000)
    if not points:
        raise ValueError(f"no canonical history for {market_name}")
    return evaluate_macd_long_flat_points_v2(
        market_id=market_id,
        market_name=market_name,
        points=points,
    )


def run_macd_dry_run_cycle_v2(*, db_path: str = "pricegauger.db") -> DryRunCycleSummaryV2:
    ensure_macd_dry_run_schema_v2()
    sources = list_subscribed_sources_v2(provider="saxo")
    markets: dict[int, str] = {}
    for source in sources:
        name = markets.setdefault(int(source.market_id), source.market_name)
        if name != source.market_name:
            raise RuntimeError(f"market_id {source.market_id} resolved to conflicting names")
    history_store = MarketHistoryStore(db_path)
    evaluated = 0
    transitions = 0
    failed = 0
    for market_id, market_name in sorted(markets.items()):
        try:
            _, emitted = evaluate_market_macd_dry_run_v2(
                market_id=market_id,
                market_name=market_name,
                history_store=history_store,
            )
            evaluated += 1
            transitions += len(emitted)
            for item in emitted:
                LOGGER.info(
                    "MACD dry-run market=%s bar=%s signal=%s action=%s state=%s->%s",
                    item.market_name,
                    item.signal_bar_time.isoformat(),
                    item.signal,
                    item.action,
                    item.prior_state,
                    item.desired_state,
                )
        except Exception as exc:
            failed += 1
            LOGGER.warning("MACD dry-run failed market=%s: %s", market_name, exc, exc_info=True)
    return DryRunCycleSummaryV2(
        attempted=len(markets),
        evaluated=evaluated,
        transitions=transitions,
        failed=failed,
    )


def run_macd_dry_run_forever_v2(
    *,
    db_path: str = "pricegauger.db",
    interval_seconds: int = 60,
) -> None:
    interval = max(30, int(interval_seconds))
    ensure_macd_dry_run_schema_v2()
    while True:
        try:
            summary = run_macd_dry_run_cycle_v2(db_path=db_path)
            LOGGER.info(
                "MACD dry-run cycle attempted=%d evaluated=%d transitions=%d failed=%d",
                summary.attempted,
                summary.evaluated,
                summary.transitions,
                summary.failed,
            )
        except Exception as exc:
            LOGGER.exception("MACD dry-run cycle failed before market evaluation: %s", exc)
        time.sleep(interval)
