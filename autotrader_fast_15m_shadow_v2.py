from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
import time
from typing import Iterable
from uuid import NAMESPACE_URL, uuid5

from autotrader_cadence_v2 import sleep_to_fixed_start_cadence_v2
from autotrader_mtf_entry_shadow_v2 import MtfObservationV2, closed_bars_v2, macd_observations_v2
from database import connect, using_postgres
from instrument_registry_v2 import list_subscribed_sources_v2
from market_history_store import MarketHistoryStore


LOGGER = logging.getLogger("pricegauger.autotrader.fast_15m_shadow_v2")

STRATEGY_KEY = "macd-15m-long-flat-shadow-v1"
TIMEFRAME_MINUTES = 15
WARMUP_DAYS = 14
BOOTSTRAP_BACKFILL_HOURS = 12

STATE_FLAT = "FLAT"
STATE_LONG = "LONG"
SIGNAL_UP = "CROSS_UP"
SIGNAL_DOWN = "CROSS_DOWN"
ACTION_WOULD_BUY = "WOULD_BUY"
ACTION_WOULD_EXIT = "WOULD_EXIT"


@dataclass(frozen=True, slots=True)
class Fast15ShadowStateV2:
    market_id: int
    market_name: str
    state: str = STATE_FLAT
    last_closed_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class Fast15ShadowEventV2:
    event_id: str
    market_id: int
    market_name: str
    action_at: datetime
    price: float
    signal: str
    action: str
    prior_state: str
    desired_state: str
    previous_macd: float
    previous_signal: float
    current_macd: float
    current_signal: float


@dataclass(frozen=True, slots=True)
class Fast15ShadowCycleSummaryV2:
    attempted: int
    evaluated: int
    events: int
    failed: int


def _utc(value: datetime | str) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _cross(previous: MtfObservationV2, current: MtfObservationV2) -> str | None:
    if previous.spread <= 0.0 < current.spread:
        return SIGNAL_UP
    if previous.spread >= 0.0 > current.spread:
        return SIGNAL_DOWN
    return None


def ensure_fast_15m_shadow_schema_v2() -> None:
    if not using_postgres():
        raise RuntimeError("Fast 15m shadow runtime requires PostgreSQL")
    with connect() as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS pg_v2_autotrader_fast15_shadow_state (
                strategy_key TEXT NOT NULL,
                market_id BIGINT NOT NULL REFERENCES pg_v2_markets(market_id),
                state TEXT NOT NULL CHECK (state IN ('FLAT','LONG')),
                last_closed_at TIMESTAMPTZ,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                PRIMARY KEY(strategy_key, market_id)
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS pg_v2_autotrader_fast15_shadow_events (
                event_id UUID PRIMARY KEY,
                strategy_key TEXT NOT NULL,
                market_id BIGINT NOT NULL REFERENCES pg_v2_markets(market_id),
                action_at TIMESTAMPTZ NOT NULL,
                price DOUBLE PRECISION NOT NULL,
                signal TEXT NOT NULL CHECK (signal IN ('CROSS_UP','CROSS_DOWN')),
                action TEXT NOT NULL CHECK (action IN ('WOULD_BUY','WOULD_EXIT')),
                prior_state TEXT NOT NULL CHECK (prior_state IN ('FLAT','LONG')),
                desired_state TEXT NOT NULL CHECK (desired_state IN ('FLAT','LONG')),
                previous_macd DOUBLE PRECISION NOT NULL,
                previous_signal DOUBLE PRECISION NOT NULL,
                current_macd DOUBLE PRECISION NOT NULL,
                current_signal DOUBLE PRECISION NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE(strategy_key, market_id, action_at, signal)
            )
            """
        )


def load_fast_15m_shadow_state_v2(*, market_id: int, market_name: str) -> Fast15ShadowStateV2:
    with connect() as db:
        row = db.execute(
            """
            SELECT state, last_closed_at
            FROM pg_v2_autotrader_fast15_shadow_state
            WHERE strategy_key = ? AND market_id = ?
            """,
            (STRATEGY_KEY, int(market_id)),
        ).fetchone()
    if row is None:
        return Fast15ShadowStateV2(market_id=int(market_id), market_name=market_name)
    values = dict(row) if isinstance(row, dict) else {"state": row[0], "last_closed_at": row[1]}
    last_closed = values.get("last_closed_at")
    return Fast15ShadowStateV2(
        market_id=int(market_id),
        market_name=market_name,
        state=str(values["state"]),
        last_closed_at=_utc(last_closed) if last_closed else None,
    )


def _event_for_cross_v2(
    *,
    state: Fast15ShadowStateV2,
    previous: MtfObservationV2,
    current: MtfObservationV2,
    signal: str,
) -> Fast15ShadowEventV2 | None:
    if signal == SIGNAL_UP and state.state == STATE_FLAT:
        action = ACTION_WOULD_BUY
        desired = STATE_LONG
    elif signal == SIGNAL_DOWN and state.state == STATE_LONG:
        action = ACTION_WOULD_EXIT
        desired = STATE_FLAT
    else:
        return None
    identity = f"{STRATEGY_KEY}|{state.market_id}|{current.closed_at.isoformat()}|{signal}"
    return Fast15ShadowEventV2(
        event_id=str(uuid5(NAMESPACE_URL, identity)),
        market_id=state.market_id,
        market_name=state.market_name,
        action_at=current.closed_at,
        price=float(current.close),
        signal=signal,
        action=action,
        prior_state=state.state,
        desired_state=desired,
        previous_macd=float(previous.macd),
        previous_signal=float(previous.signal),
        current_macd=float(current.macd),
        current_signal=float(current.signal),
    )


def _persist_progress_v2(
    *,
    state: Fast15ShadowStateV2,
    current: MtfObservationV2,
    event: Fast15ShadowEventV2 | None,
) -> Fast15ShadowStateV2:
    next_state = state.state if event is None else event.desired_state
    with connect() as db:
        if event is not None:
            db.execute(
                """
                INSERT INTO pg_v2_autotrader_fast15_shadow_events(
                    event_id, strategy_key, market_id, action_at, price, signal, action,
                    prior_state, desired_state, previous_macd, previous_signal,
                    current_macd, current_signal
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (event_id) DO NOTHING
                """,
                (
                    event.event_id,
                    STRATEGY_KEY,
                    event.market_id,
                    event.action_at,
                    event.price,
                    event.signal,
                    event.action,
                    event.prior_state,
                    event.desired_state,
                    event.previous_macd,
                    event.previous_signal,
                    event.current_macd,
                    event.current_signal,
                ),
            )
        db.execute(
            """
            INSERT INTO pg_v2_autotrader_fast15_shadow_state(
                strategy_key, market_id, state, last_closed_at, updated_at
            ) VALUES (?, ?, ?, ?, now())
            ON CONFLICT (strategy_key, market_id) DO UPDATE SET
                state=EXCLUDED.state,
                last_closed_at=EXCLUDED.last_closed_at,
                updated_at=now()
            """,
            (STRATEGY_KEY, state.market_id, next_state, current.closed_at),
        )
    return Fast15ShadowStateV2(
        market_id=state.market_id,
        market_name=state.market_name,
        state=next_state,
        last_closed_at=current.closed_at,
    )


def evaluate_fast_15m_shadow_points_v2(
    *,
    market_id: int,
    market_name: str,
    points: Iterable[tuple[str, float]],
    now: datetime | None = None,
) -> tuple[Fast15ShadowStateV2, tuple[Fast15ShadowEventV2, ...]]:
    materialized = tuple(points)
    if not materialized:
        raise ValueError("Fast 15m shadow requires canonical history")
    bars = closed_bars_v2(materialized, market=market_name, timeframe_minutes=TIMEFRAME_MINUTES)
    observations = macd_observations_v2(bars, timeframe_minutes=TIMEFRAME_MINUTES)
    if len(observations) < 2:
        raise ValueError("Fast 15m shadow needs enough closed 15m bars for MACD 12/26/9")

    state = load_fast_15m_shadow_state_v2(market_id=market_id, market_name=market_name)
    end = _utc(now or datetime.now(timezone.utc))
    bootstrap_floor = end - timedelta(hours=BOOTSTRAP_BACKFILL_HOURS)
    events: list[Fast15ShadowEventV2] = []
    for previous, current in zip(observations, observations[1:]):
        if current.closed_at > end:
            continue
        if state.last_closed_at is not None and current.closed_at <= state.last_closed_at:
            continue
        if state.last_closed_at is None and current.closed_at < bootstrap_floor:
            continue
        signal = _cross(previous, current)
        event = None if signal is None else _event_for_cross_v2(
            state=state,
            previous=previous,
            current=current,
            signal=signal,
        )
        if event is not None:
            events.append(event)
        state = _persist_progress_v2(state=state, current=current, event=event)
    return state, tuple(events)


def evaluate_market_fast_15m_shadow_v2(
    *,
    market_id: int,
    market_name: str,
    history_store: MarketHistoryStore,
    now: datetime | None = None,
) -> tuple[Fast15ShadowStateV2, tuple[Fast15ShadowEventV2, ...]]:
    end = _utc(now or datetime.now(timezone.utc))
    start = end - timedelta(days=WARMUP_DAYS)
    points = history_store.load_range(market=market_name, start=start, end=end, limit=100_000)
    if not points:
        raise ValueError(f"no canonical history for {market_name}")
    return evaluate_fast_15m_shadow_points_v2(
        market_id=market_id,
        market_name=market_name,
        points=points,
        now=end,
    )


def run_fast_15m_shadow_cycle_v2(*, db_path: str = "pricegauger.db") -> Fast15ShadowCycleSummaryV2:
    ensure_fast_15m_shadow_schema_v2()
    sources = list_subscribed_sources_v2(provider="saxo")
    markets: dict[int, str] = {}
    for source in sources:
        name = markets.setdefault(int(source.market_id), source.market_name)
        if name != source.market_name:
            raise RuntimeError(f"market_id {source.market_id} resolved to conflicting names")

    history_store = MarketHistoryStore(db_path)
    evaluated = 0
    event_count = 0
    failed = 0
    for market_id, market_name in sorted(markets.items()):
        try:
            state, events = evaluate_market_fast_15m_shadow_v2(
                market_id=market_id,
                market_name=market_name,
                history_store=history_store,
            )
            evaluated += 1
            event_count += len(events)
            for event in events:
                LOGGER.info(
                    "Fast15 shadow market=%s at=%s signal=%s action=%s state=%s->%s price=%.5f spread=%.8f",
                    event.market_name,
                    event.action_at.isoformat(),
                    event.signal,
                    event.action,
                    event.prior_state,
                    event.desired_state,
                    event.price,
                    event.current_macd - event.current_signal,
                )
            if not events:
                LOGGER.debug("Fast15 shadow market=%s state=%s no new event", market_name, state.state)
        except Exception as exc:
            failed += 1
            LOGGER.warning("Fast15 shadow failed market=%s: %s", market_name, exc, exc_info=True)

    return Fast15ShadowCycleSummaryV2(
        attempted=len(markets),
        evaluated=evaluated,
        events=event_count,
        failed=failed,
    )


def run_fast_15m_shadow_forever_v2(
    *,
    db_path: str = "pricegauger.db",
    interval_seconds: int = 30,
) -> None:
    interval = max(10, int(interval_seconds))
    ensure_fast_15m_shadow_schema_v2()
    while True:
        started = time.monotonic()
        try:
            summary = run_fast_15m_shadow_cycle_v2(db_path=db_path)
            LOGGER.info(
                "Fast15 shadow cycle attempted=%d evaluated=%d events=%d failed=%d",
                summary.attempted,
                summary.evaluated,
                summary.events,
                summary.failed,
            )
        except Exception as exc:
            LOGGER.exception("Fast15 shadow cycle failed before market evaluation: %s", exc)
        sleep_to_fixed_start_cadence_v2(started, interval)


__all__ = [
    "ACTION_WOULD_BUY",
    "ACTION_WOULD_EXIT",
    "Fast15ShadowCycleSummaryV2",
    "Fast15ShadowEventV2",
    "Fast15ShadowStateV2",
    "SIGNAL_DOWN",
    "SIGNAL_UP",
    "STATE_FLAT",
    "STATE_LONG",
    "STRATEGY_KEY",
    "TIMEFRAME_MINUTES",
    "evaluate_fast_15m_shadow_points_v2",
    "run_fast_15m_shadow_cycle_v2",
    "run_fast_15m_shadow_forever_v2",
]
