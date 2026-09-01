from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
import time
from typing import Iterable
from uuid import NAMESPACE_URL, uuid5

from autotrader_cadence_v2 import sleep_to_fixed_start_cadence_v2
from database import connect, using_postgres
from instrument_registry_v2 import list_subscribed_sources_v2
from market_history_store import MarketHistoryStore
from trading_desk import ChartBar
from trading_desk_indicators import calculate_indicators


LOGGER = logging.getLogger("pricegauger.autotrader.intrabar30_shadow_v2")

STRATEGY_KEY = "macd-30m-intrabar-1m-long-flat-shadow-v1"
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
WARMUP_DAYS = 14
BOOTSTRAP_BACKFILL_HOURS = 12

STATE_FLAT = "FLAT"
STATE_LONG = "LONG"
SIGNAL_UP = "CROSS_UP"
SIGNAL_DOWN = "CROSS_DOWN"
ACTION_WOULD_BUY = "WOULD_BUY"
ACTION_WOULD_EXIT = "WOULD_EXIT"
SOURCE_KIND = "CANONICAL_1M_CLOSE"


@dataclass(frozen=True, slots=True)
class IntrabarMacdSampleV2:
    action_at: datetime
    bucket_start: datetime
    minute_offset: int
    price: float
    macd: float
    signal: float

    @property
    def spread(self) -> float:
        return float(self.macd - self.signal)


@dataclass(frozen=True, slots=True)
class Intrabar30ShadowStateV2:
    market_id: int
    market_name: str
    state: str = STATE_FLAT
    last_sample_at: datetime | None = None
    last_spread: float | None = None


@dataclass(frozen=True, slots=True)
class Intrabar30ShadowEventV2:
    event_id: str
    market_id: int
    market_name: str
    action_at: datetime
    bucket_start: datetime
    minute_offset: int
    price: float
    signal: str
    action: str
    prior_state: str
    desired_state: str
    previous_spread: float
    current_spread: float
    current_macd: float
    current_signal: float


@dataclass(frozen=True, slots=True)
class Intrabar30ShadowCycleSummaryV2:
    attempted: int
    evaluated: int
    events: int
    failed: int


def _utc(value: datetime | str) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _bucket_start_30m(stamp: datetime) -> datetime:
    value = _utc(stamp)
    return value.replace(minute=(value.minute // 30) * 30, second=0, microsecond=0)


def _bar(
    *,
    market: str,
    bucket_start: datetime,
    open_price: float,
    high: float,
    low: float,
    close: float,
) -> ChartBar:
    return ChartBar(
        market=market,
        bar_time=bucket_start.isoformat(),
        open=float(open_price),
        high=float(high),
        low=float(low),
        close=float(close),
        volume=None,
    )


def intrabar_macd_samples_v2(
    points: Iterable[tuple[str, float]],
    *,
    market: str,
    sample_floor: datetime | None = None,
) -> tuple[IntrabarMacdSampleV2, ...]:
    """Sample a forming 30m MACD on each fully observed canonical 1m close.

    The historical 30m bars before the current bucket are final. The current 30m
    bucket is deliberately *forming*: its close is replaced by the latest canonical
    1m close. This gives a deterministic, replayable clock for the first observed
    intrabar MACD cross. It does not pretend that 1m history is tick/second data.
    """
    normalized = sorted((_utc(stamp), float(price)) for stamp, price in points)
    if not normalized:
        return ()
    floor = None if sample_floor is None else _utc(sample_floor)

    completed: list[ChartBar] = []
    current_bucket: datetime | None = None
    current_open = 0.0
    current_high = 0.0
    current_low = 0.0
    current_close = 0.0
    samples: list[IntrabarMacdSampleV2] = []

    for stamp, price in normalized:
        bucket = _bucket_start_30m(stamp)
        if current_bucket is None or bucket != current_bucket:
            if current_bucket is not None:
                completed.append(
                    _bar(
                        market=market,
                        bucket_start=current_bucket,
                        open_price=current_open,
                        high=current_high,
                        low=current_low,
                        close=current_close,
                    )
                )
            current_bucket = bucket
            current_open = current_high = current_low = current_close = float(price)
        else:
            current_high = max(current_high, float(price))
            current_low = min(current_low, float(price))
            current_close = float(price)

        action_at = stamp.replace(second=0, microsecond=0) + timedelta(minutes=1)
        if floor is not None and action_at < floor:
            continue

        forming = _bar(
            market=market,
            bucket_start=current_bucket,
            open_price=current_open,
            high=current_high,
            low=current_low,
            close=current_close,
        )
        indicators = calculate_indicators(
            tuple(completed) + (forming,),
            macd_fast=MACD_FAST,
            macd_slow=MACD_SLOW,
            macd_signal=MACD_SIGNAL,
        )
        if not indicators.macd or not indicators.macd_signal:
            continue
        macd_point = indicators.macd[-1]
        signal_point = indicators.macd_signal[-1]
        if macd_point.bar_time != forming.bar_time or signal_point.bar_time != forming.bar_time:
            continue
        minute_offset = int((action_at - current_bucket).total_seconds() // 60)
        if minute_offset < 1 or minute_offset > 30:
            raise RuntimeError(f"invalid intrabar minute offset: {minute_offset}")
        samples.append(
            IntrabarMacdSampleV2(
                action_at=action_at,
                bucket_start=current_bucket,
                minute_offset=minute_offset,
                price=float(current_close),
                macd=float(macd_point.value),
                signal=float(signal_point.value),
            )
        )
    return tuple(samples)


def _cross_spread_v2(previous_spread: float, current_spread: float) -> str | None:
    if float(previous_spread) <= 0.0 < float(current_spread):
        return SIGNAL_UP
    if float(previous_spread) >= 0.0 > float(current_spread):
        return SIGNAL_DOWN
    return None


def ensure_intrabar30_shadow_schema_v2() -> None:
    if not using_postgres():
        raise RuntimeError("Intrabar30 shadow runtime requires PostgreSQL")
    with connect() as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS pg_v2_autotrader_intrabar30_shadow_state (
                strategy_key TEXT NOT NULL,
                market_id BIGINT NOT NULL REFERENCES pg_v2_markets(market_id),
                state TEXT NOT NULL CHECK (state IN ('FLAT','LONG')),
                last_sample_at TIMESTAMPTZ,
                last_spread DOUBLE PRECISION,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                PRIMARY KEY(strategy_key, market_id)
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS pg_v2_autotrader_intrabar30_shadow_events (
                event_id UUID PRIMARY KEY,
                strategy_key TEXT NOT NULL,
                market_id BIGINT NOT NULL REFERENCES pg_v2_markets(market_id),
                action_at TIMESTAMPTZ NOT NULL,
                bucket_start TIMESTAMPTZ NOT NULL,
                minute_offset INTEGER NOT NULL CHECK (minute_offset BETWEEN 1 AND 30),
                price DOUBLE PRECISION NOT NULL,
                signal TEXT NOT NULL CHECK (signal IN ('CROSS_UP','CROSS_DOWN')),
                action TEXT NOT NULL CHECK (action IN ('WOULD_BUY','WOULD_EXIT')),
                prior_state TEXT NOT NULL CHECK (prior_state IN ('FLAT','LONG')),
                desired_state TEXT NOT NULL CHECK (desired_state IN ('FLAT','LONG')),
                previous_spread DOUBLE PRECISION NOT NULL,
                current_spread DOUBLE PRECISION NOT NULL,
                current_macd DOUBLE PRECISION NOT NULL,
                current_signal DOUBLE PRECISION NOT NULL,
                source_kind TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE(strategy_key, market_id, action_at, signal)
            )
            """
        )


def load_intrabar30_shadow_state_v2(*, market_id: int, market_name: str) -> Intrabar30ShadowStateV2:
    with connect() as db:
        row = db.execute(
            """
            SELECT state, last_sample_at, last_spread
            FROM pg_v2_autotrader_intrabar30_shadow_state
            WHERE strategy_key = ? AND market_id = ?
            """,
            (STRATEGY_KEY, int(market_id)),
        ).fetchone()
    if row is None:
        return Intrabar30ShadowStateV2(market_id=int(market_id), market_name=market_name)
    values = dict(row) if isinstance(row, dict) else {
        "state": row[0],
        "last_sample_at": row[1],
        "last_spread": row[2],
    }
    return Intrabar30ShadowStateV2(
        market_id=int(market_id),
        market_name=market_name,
        state=str(values["state"]),
        last_sample_at=_utc(values["last_sample_at"]) if values.get("last_sample_at") else None,
        last_spread=None if values.get("last_spread") is None else float(values["last_spread"]),
    )


def _event_for_cross_v2(
    *,
    state: Intrabar30ShadowStateV2,
    sample: IntrabarMacdSampleV2,
    previous_spread: float,
    signal: str,
) -> Intrabar30ShadowEventV2 | None:
    if signal == SIGNAL_UP and state.state == STATE_FLAT:
        action = ACTION_WOULD_BUY
        desired = STATE_LONG
    elif signal == SIGNAL_DOWN and state.state == STATE_LONG:
        action = ACTION_WOULD_EXIT
        desired = STATE_FLAT
    else:
        return None
    identity = f"{STRATEGY_KEY}|{state.market_id}|{sample.action_at.isoformat()}|{signal}"
    return Intrabar30ShadowEventV2(
        event_id=str(uuid5(NAMESPACE_URL, identity)),
        market_id=state.market_id,
        market_name=state.market_name,
        action_at=sample.action_at,
        bucket_start=sample.bucket_start,
        minute_offset=sample.minute_offset,
        price=sample.price,
        signal=signal,
        action=action,
        prior_state=state.state,
        desired_state=desired,
        previous_spread=float(previous_spread),
        current_spread=float(sample.spread),
        current_macd=float(sample.macd),
        current_signal=float(sample.signal),
    )


def _persist_progress_v2(
    *,
    state: Intrabar30ShadowStateV2,
    sample: IntrabarMacdSampleV2,
    event: Intrabar30ShadowEventV2 | None,
) -> Intrabar30ShadowStateV2:
    next_state = state.state if event is None else event.desired_state
    with connect() as db:
        if event is not None:
            db.execute(
                """
                INSERT INTO pg_v2_autotrader_intrabar30_shadow_events(
                    event_id, strategy_key, market_id, action_at, bucket_start, minute_offset,
                    price, signal, action, prior_state, desired_state, previous_spread,
                    current_spread, current_macd, current_signal, source_kind
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (event_id) DO NOTHING
                """,
                (
                    event.event_id,
                    STRATEGY_KEY,
                    event.market_id,
                    event.action_at,
                    event.bucket_start,
                    event.minute_offset,
                    event.price,
                    event.signal,
                    event.action,
                    event.prior_state,
                    event.desired_state,
                    event.previous_spread,
                    event.current_spread,
                    event.current_macd,
                    event.current_signal,
                    SOURCE_KIND,
                ),
            )
        db.execute(
            """
            INSERT INTO pg_v2_autotrader_intrabar30_shadow_state(
                strategy_key, market_id, state, last_sample_at, last_spread, updated_at
            ) VALUES (?, ?, ?, ?, ?, now())
            ON CONFLICT (strategy_key, market_id) DO UPDATE SET
                state=EXCLUDED.state,
                last_sample_at=EXCLUDED.last_sample_at,
                last_spread=EXCLUDED.last_spread,
                updated_at=now()
            """,
            (STRATEGY_KEY, state.market_id, next_state, sample.action_at, sample.spread),
        )
    return Intrabar30ShadowStateV2(
        market_id=state.market_id,
        market_name=state.market_name,
        state=next_state,
        last_sample_at=sample.action_at,
        last_spread=sample.spread,
    )


def evaluate_intrabar30_shadow_points_v2(
    *,
    market_id: int,
    market_name: str,
    points: Iterable[tuple[str, float]],
    now: datetime | None = None,
) -> tuple[Intrabar30ShadowStateV2, tuple[Intrabar30ShadowEventV2, ...]]:
    materialized = tuple(points)
    if not materialized:
        raise ValueError("Intrabar30 shadow requires canonical history")
    state = load_intrabar30_shadow_state_v2(market_id=market_id, market_name=market_name)
    end = _utc(now or datetime.now(timezone.utc))
    if state.last_sample_at is None:
        sample_floor = end - timedelta(hours=BOOTSTRAP_BACKFILL_HOURS, minutes=1)
    else:
        sample_floor = state.last_sample_at + timedelta(microseconds=1)
    samples = intrabar_macd_samples_v2(materialized, market=market_name, sample_floor=sample_floor)

    events: list[Intrabar30ShadowEventV2] = []
    for sample in samples:
        if sample.action_at > end:
            continue
        if state.last_sample_at is not None and sample.action_at <= state.last_sample_at:
            continue
        previous_spread = state.last_spread
        signal = None if previous_spread is None else _cross_spread_v2(previous_spread, sample.spread)
        event = None if signal is None else _event_for_cross_v2(
            state=state,
            sample=sample,
            previous_spread=float(previous_spread),
            signal=signal,
        )
        if event is not None:
            events.append(event)
        state = _persist_progress_v2(state=state, sample=sample, event=event)
    return state, tuple(events)


def evaluate_market_intrabar30_shadow_v2(
    *,
    market_id: int,
    market_name: str,
    history_store: MarketHistoryStore,
    now: datetime | None = None,
) -> tuple[Intrabar30ShadowStateV2, tuple[Intrabar30ShadowEventV2, ...]]:
    end = _utc(now or datetime.now(timezone.utc))
    start = end - timedelta(days=WARMUP_DAYS)
    points = history_store.load_range(market=market_name, start=start, end=end, limit=100_000)
    if not points:
        raise ValueError(f"no canonical history for {market_name}")
    return evaluate_intrabar30_shadow_points_v2(
        market_id=market_id,
        market_name=market_name,
        points=points,
        now=end,
    )


def run_intrabar30_shadow_cycle_v2(*, db_path: str = "pricegauger.db") -> Intrabar30ShadowCycleSummaryV2:
    ensure_intrabar30_shadow_schema_v2()
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
            state, events = evaluate_market_intrabar30_shadow_v2(
                market_id=market_id,
                market_name=market_name,
                history_store=history_store,
            )
            evaluated += 1
            event_count += len(events)
            for event in events:
                LOGGER.info(
                    "Intrabar30 shadow market=%s at=%s bucket=%s minute=%d signal=%s action=%s state=%s->%s price=%.5f spread=%.8f source=%s",
                    event.market_name,
                    event.action_at.isoformat(),
                    event.bucket_start.isoformat(),
                    event.minute_offset,
                    event.signal,
                    event.action,
                    event.prior_state,
                    event.desired_state,
                    event.price,
                    event.current_spread,
                    SOURCE_KIND,
                )
            if not events:
                LOGGER.debug("Intrabar30 shadow market=%s state=%s no new event", market_name, state.state)
        except Exception as exc:
            failed += 1
            LOGGER.warning("Intrabar30 shadow failed market=%s: %s", market_name, exc, exc_info=True)

    return Intrabar30ShadowCycleSummaryV2(
        attempted=len(markets),
        evaluated=evaluated,
        events=event_count,
        failed=failed,
    )


def run_intrabar30_shadow_forever_v2(
    *,
    db_path: str = "pricegauger.db",
    interval_seconds: int = 10,
) -> None:
    interval = max(5, int(interval_seconds))
    ensure_intrabar30_shadow_schema_v2()
    while True:
        started = time.monotonic()
        try:
            summary = run_intrabar30_shadow_cycle_v2(db_path=db_path)
            LOGGER.info(
                "Intrabar30 shadow cycle attempted=%d evaluated=%d events=%d failed=%d",
                summary.attempted,
                summary.evaluated,
                summary.events,
                summary.failed,
            )
        except Exception as exc:
            LOGGER.exception("Intrabar30 shadow cycle failed before market evaluation: %s", exc)
        sleep_to_fixed_start_cadence_v2(started, interval)


__all__ = [
    "ACTION_WOULD_BUY",
    "ACTION_WOULD_EXIT",
    "Intrabar30ShadowCycleSummaryV2",
    "Intrabar30ShadowEventV2",
    "Intrabar30ShadowStateV2",
    "IntrabarMacdSampleV2",
    "SIGNAL_DOWN",
    "SIGNAL_UP",
    "SOURCE_KIND",
    "STATE_FLAT",
    "STATE_LONG",
    "STRATEGY_KEY",
    "evaluate_intrabar30_shadow_points_v2",
    "intrabar_macd_samples_v2",
    "run_intrabar30_shadow_cycle_v2",
    "run_intrabar30_shadow_forever_v2",
]
