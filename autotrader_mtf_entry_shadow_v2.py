from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
import logging
import time
from typing import Iterable
from uuid import NAMESPACE_URL, uuid5

import pandas as pd

from autotrader_cadence_v2 import sleep_to_fixed_start_cadence_v2
from database import connect, using_postgres
from instrument_registry_v2 import list_subscribed_sources_v2
from market_history_store import MarketHistoryStore
from timeframe_contract_v2 import normalize_canonical_1m_v2
from trading_desk import ChartBar
from trading_desk_indicators import calculate_indicators


LOGGER = logging.getLogger("pricegauger.autotrader.mtf_entry_shadow_v2")

STRATEGY_KEY = "macd-mtf-long-entry-shadow-v1"
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
ENTRY_TIMEFRAME_MINUTES = 5
VALIDATION_TIMEFRAME_MINUTES = 10
REGIME_TIMEFRAME_MINUTES = 30
WARMUP_DAYS = 14
BOOTSTRAP_BACKFILL_HOURS = 12

STATE_FLAT = "FLAT"
STATE_PROVISIONAL_LONG = "PROVISIONAL_LONG"
STATE_VALIDATED_10M = "VALIDATED_10M"
STATE_CONFIRMED_30M = "CONFIRMED_30M"
_LONG_STATES = {STATE_PROVISIONAL_LONG, STATE_VALIDATED_10M, STATE_CONFIRMED_30M}

CONTEXT_BULLISH = "BULLISH"
CONTEXT_RECOVERING = "RECOVERING"
CONTEXT_BEARISH = "BEARISH"
CONTEXT_UNKNOWN = "UNKNOWN"
_ALLOWED_ENTRY_CONTEXTS = {CONTEXT_BULLISH, CONTEXT_RECOVERING}

EVENT_ENTRY_5M = "ENTRY_5M"
EVENT_REJECT_5M = "REJECT_5M"
EVENT_CONFIRM_10M = "CONFIRM_10M"
EVENT_REJECT_10M = "REJECT_10M"
EVENT_CONFIRM_30M = "CONFIRM_30M"
EVENT_EXIT_30M = "EXIT_30M"

ACTION_WOULD_BUY = "WOULD_BUY"
ACTION_WOULD_EXIT_REARM = "WOULD_EXIT_REARM"
ACTION_CONFIRMATION = "CONFIRMATION"
ACTION_WOULD_EXIT = "WOULD_EXIT"


@dataclass(frozen=True, slots=True)
class MtfObservationV2:
    bar_time: datetime
    closed_at: datetime
    timeframe_minutes: int
    close: float
    macd: float
    signal: float

    @property
    def spread(self) -> float:
        return self.macd - self.signal


@dataclass(frozen=True, slots=True)
class MtfShadowStateV2:
    market_id: int
    market_name: str
    state: str = STATE_FLAT
    last_5m_closed_at: datetime | None = None
    last_10m_closed_at: datetime | None = None
    last_30m_closed_at: datetime | None = None
    entry_at: datetime | None = None
    entry_price: float | None = None


@dataclass(frozen=True, slots=True)
class MtfDecisionV2:
    event_type: str
    action: str
    desired_state: str
    reason: str


@dataclass(frozen=True, slots=True)
class MtfShadowEventV2:
    event_id: str
    market_id: int
    market_name: str
    event_type: str
    action: str
    action_at: datetime
    price: float
    prior_state: str
    desired_state: str
    reason: str
    context_30m: str
    spread_5m: float | None
    spread_10m: float | None
    spread_30m: float | None


@dataclass(frozen=True, slots=True)
class MtfShadowCycleSummaryV2:
    attempted: int
    evaluated: int
    events: int
    failed: int


def _utc(value: datetime | str) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def closed_bars_v2(
    points: Iterable[tuple[str, float]],
    *,
    market: str,
    timeframe_minutes: int,
) -> tuple[ChartBar, ...]:
    """Build fully closed epoch-aligned bars from canonical 1m observations.

    This deliberately mirrors the established closed-30m AutoTrader contract while
    making the bucket size explicit. Forming bars are never eligible for shadow
    decisions. No execution authority exists in this module.
    """
    minutes = int(timeframe_minutes)
    if minutes <= 0:
        raise ValueError("timeframe_minutes must be positive")
    one = normalize_canonical_1m_v2(points)
    latest = one["timestamp"].iloc[-1]
    observed_through = latest.floor("min") + pd.Timedelta(minutes=1)
    aggregated = (
        one.set_index("timestamp")
        .resample(f"{minutes}min", label="left", closed="left", origin="epoch")
        .agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"))
        .dropna(subset=["close"])
    )
    if aggregated.empty:
        return ()
    aggregated = aggregated.loc[(aggregated.index + pd.Timedelta(minutes=minutes)) <= observed_through]
    return tuple(
        ChartBar(
            market=market,
            bar_time=stamp.to_pydatetime().astimezone(timezone.utc).isoformat(),
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=None,
        )
        for stamp, row in aggregated.iterrows()
    )


def macd_observations_v2(
    bars: tuple[ChartBar, ...],
    *,
    timeframe_minutes: int,
) -> tuple[MtfObservationV2, ...]:
    indicators = calculate_indicators(
        bars,
        macd_fast=MACD_FAST,
        macd_slow=MACD_SLOW,
        macd_signal=MACD_SIGNAL,
    )
    macd_by_time = {_utc(point.bar_time): point.value for point in indicators.macd}
    signal_by_time = {_utc(point.bar_time): point.value for point in indicators.macd_signal}
    close_by_time = {_utc(bar.bar_time): float(bar.close) for bar in bars}
    minutes = int(timeframe_minutes)
    return tuple(
        MtfObservationV2(
            bar_time=stamp,
            closed_at=stamp + timedelta(minutes=minutes),
            timeframe_minutes=minutes,
            close=close_by_time[stamp],
            macd=float(macd_by_time[stamp]),
            signal=float(signal_by_time[stamp]),
        )
        for stamp in sorted(set(macd_by_time).intersection(signal_by_time).intersection(close_by_time))
    )


def _cross(previous: MtfObservationV2, current: MtfObservationV2) -> str | None:
    if previous.spread <= 0.0 < current.spread:
        return "CROSS_UP"
    if previous.spread >= 0.0 > current.spread:
        return "CROSS_DOWN"
    return None


def regime_context_30m_v2(
    previous: MtfObservationV2 | None,
    current: MtfObservationV2 | None,
) -> str:
    """Classify 30m as bullish, recovering, bearish, or unknown.

    Recovering is intentionally less strict than a full 30m CROSS_UP: MACD may still
    be below its signal, but bearish spread must be shrinking on closed 30m bars.
    This is the context in which the user's faster 5m trigger is allowed to act.
    """
    if previous is None or current is None:
        return CONTEXT_UNKNOWN
    if current.spread > 0.0:
        return CONTEXT_BULLISH
    if current.spread > previous.spread:
        return CONTEXT_RECOVERING
    return CONTEXT_BEARISH


def decision_for_observation_v2(
    *,
    state: str,
    timeframe_minutes: int,
    previous: MtfObservationV2,
    current: MtfObservationV2,
    context_30m: str,
) -> MtfDecisionV2 | None:
    """Pure hierarchical decision policy; all inputs must be closed-bar observations."""
    crossing = _cross(previous, current)
    timeframe = int(timeframe_minutes)

    if timeframe == ENTRY_TIMEFRAME_MINUTES:
        if state == STATE_FLAT and crossing == "CROSS_UP" and context_30m in _ALLOWED_ENTRY_CONTEXTS:
            return MtfDecisionV2(
                event_type=EVENT_ENTRY_5M,
                action=ACTION_WOULD_BUY,
                desired_state=STATE_PROVISIONAL_LONG,
                reason=f"closed 5m CROSS_UP inside 30m {context_30m.lower()} context",
            )
        if state == STATE_PROVISIONAL_LONG and crossing == "CROSS_DOWN":
            return MtfDecisionV2(
                event_type=EVENT_REJECT_5M,
                action=ACTION_WOULD_EXIT_REARM,
                desired_state=STATE_FLAT,
                reason="5m trigger failed before 10m validation; exit small and re-arm",
            )
        return None

    if timeframe == VALIDATION_TIMEFRAME_MINUTES:
        if state == STATE_PROVISIONAL_LONG and current.spread > 0.0:
            return MtfDecisionV2(
                event_type=EVENT_CONFIRM_10M,
                action=ACTION_CONFIRMATION,
                desired_state=STATE_VALIDATED_10M,
                reason="closed 10m MACD is bullish after provisional 5m entry",
            )
        if state == STATE_VALIDATED_10M and crossing == "CROSS_DOWN":
            return MtfDecisionV2(
                event_type=EVENT_REJECT_10M,
                action=ACTION_WOULD_EXIT_REARM,
                desired_state=STATE_FLAT,
                reason="10m validation reversed before 30m regime confirmation; exit and re-arm",
            )
        return None

    if timeframe == REGIME_TIMEFRAME_MINUTES:
        if state in _LONG_STATES and crossing == "CROSS_DOWN":
            return MtfDecisionV2(
                event_type=EVENT_EXIT_30M,
                action=ACTION_WOULD_EXIT,
                desired_state=STATE_FLAT,
                reason="closed 30m bearish cross ends the long regime",
            )
        if state in {STATE_PROVISIONAL_LONG, STATE_VALIDATED_10M} and crossing == "CROSS_UP":
            return MtfDecisionV2(
                event_type=EVENT_CONFIRM_30M,
                action=ACTION_CONFIRMATION,
                desired_state=STATE_CONFIRMED_30M,
                reason="closed 30m CROSS_UP confirms the long regime",
            )
        return None

    raise ValueError(f"unsupported MTF timeframe: {timeframe}")


def ensure_mtf_entry_shadow_schema_v2() -> None:
    if not using_postgres():
        raise RuntimeError("MTF entry shadow runtime requires PostgreSQL")
    with connect() as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS pg_v2_autotrader_mtf_shadow_state (
                strategy_key TEXT NOT NULL,
                market_id BIGINT NOT NULL REFERENCES pg_v2_markets(market_id),
                state TEXT NOT NULL CHECK (state IN ('FLAT','PROVISIONAL_LONG','VALIDATED_10M','CONFIRMED_30M')),
                last_5m_closed_at TIMESTAMPTZ,
                last_10m_closed_at TIMESTAMPTZ,
                last_30m_closed_at TIMESTAMPTZ,
                entry_at TIMESTAMPTZ,
                entry_price DOUBLE PRECISION,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                PRIMARY KEY(strategy_key, market_id)
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS pg_v2_autotrader_mtf_shadow_events (
                event_id UUID PRIMARY KEY,
                strategy_key TEXT NOT NULL,
                market_id BIGINT NOT NULL REFERENCES pg_v2_markets(market_id),
                event_type TEXT NOT NULL,
                action TEXT NOT NULL,
                action_at TIMESTAMPTZ NOT NULL,
                price DOUBLE PRECISION NOT NULL,
                prior_state TEXT NOT NULL,
                desired_state TEXT NOT NULL,
                reason TEXT NOT NULL,
                context_30m TEXT NOT NULL,
                spread_5m DOUBLE PRECISION,
                spread_10m DOUBLE PRECISION,
                spread_30m DOUBLE PRECISION,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE(strategy_key, market_id, event_type, action_at)
            )
            """
        )


def _row_dict(row):
    return dict(row) if row is not None and not isinstance(row, dict) else row


def load_mtf_shadow_state_v2(*, market_id: int, market_name: str) -> MtfShadowStateV2:
    with connect() as db:
        row = db.execute(
            """
            SELECT state, last_5m_closed_at, last_10m_closed_at, last_30m_closed_at,
                   entry_at, entry_price
            FROM pg_v2_autotrader_mtf_shadow_state
            WHERE strategy_key = ? AND market_id = ?
            """,
            (STRATEGY_KEY, int(market_id)),
        ).fetchone()
    item = _row_dict(row)
    if item is None:
        return MtfShadowStateV2(market_id=int(market_id), market_name=market_name)
    return MtfShadowStateV2(
        market_id=int(market_id),
        market_name=market_name,
        state=str(item["state"]),
        last_5m_closed_at=_utc(item["last_5m_closed_at"]) if item["last_5m_closed_at"] else None,
        last_10m_closed_at=_utc(item["last_10m_closed_at"]) if item["last_10m_closed_at"] else None,
        last_30m_closed_at=_utc(item["last_30m_closed_at"]) if item["last_30m_closed_at"] else None,
        entry_at=_utc(item["entry_at"]) if item["entry_at"] else None,
        entry_price=None if item["entry_price"] is None else float(item["entry_price"]),
    )


def _latest_at(
    observations: tuple[MtfObservationV2, ...],
    at: datetime,
) -> MtfObservationV2 | None:
    latest = None
    for item in observations:
        if item.closed_at > at:
            break
        latest = item
    return latest


def _latest_pair_at(
    observations: tuple[MtfObservationV2, ...],
    at: datetime,
) -> tuple[MtfObservationV2 | None, MtfObservationV2 | None]:
    eligible = [item for item in observations if item.closed_at <= at]
    if len(eligible) < 2:
        return None, eligible[-1] if eligible else None
    return eligible[-2], eligible[-1]


def _event_from_decision_v2(
    *,
    state: MtfShadowStateV2,
    observation: MtfObservationV2,
    decision: MtfDecisionV2,
    context_30m: str,
    latest_5m: MtfObservationV2 | None,
    latest_10m: MtfObservationV2 | None,
    latest_30m: MtfObservationV2 | None,
) -> MtfShadowEventV2:
    identity = (
        f"{STRATEGY_KEY}|{state.market_id}|{decision.event_type}|"
        f"{observation.closed_at.isoformat()}"
    )
    return MtfShadowEventV2(
        event_id=str(uuid5(NAMESPACE_URL, identity)),
        market_id=state.market_id,
        market_name=state.market_name,
        event_type=decision.event_type,
        action=decision.action,
        action_at=observation.closed_at,
        price=float(observation.close),
        prior_state=state.state,
        desired_state=decision.desired_state,
        reason=decision.reason,
        context_30m=context_30m,
        spread_5m=None if latest_5m is None else float(latest_5m.spread),
        spread_10m=None if latest_10m is None else float(latest_10m.spread),
        spread_30m=None if latest_30m is None else float(latest_30m.spread),
    )


def _persist_progress_v2(
    *,
    state: MtfShadowStateV2,
    observation: MtfObservationV2,
    event: MtfShadowEventV2 | None,
) -> MtfShadowStateV2:
    next_state = state.state if event is None else event.desired_state
    entry_at = state.entry_at
    entry_price = state.entry_price
    if event is not None and event.event_type == EVENT_ENTRY_5M:
        entry_at = event.action_at
        entry_price = event.price
    elif event is not None and event.desired_state == STATE_FLAT:
        entry_at = None
        entry_price = None

    updates = {
        ENTRY_TIMEFRAME_MINUTES: {"last_5m_closed_at": observation.closed_at},
        VALIDATION_TIMEFRAME_MINUTES: {"last_10m_closed_at": observation.closed_at},
        REGIME_TIMEFRAME_MINUTES: {"last_30m_closed_at": observation.closed_at},
    }[observation.timeframe_minutes]
    next_value = replace(
        state,
        state=next_state,
        entry_at=entry_at,
        entry_price=entry_price,
        **updates,
    )

    with connect() as db:
        if event is not None:
            db.execute(
                """
                INSERT INTO pg_v2_autotrader_mtf_shadow_events(
                    event_id, strategy_key, market_id, event_type, action, action_at,
                    price, prior_state, desired_state, reason, context_30m,
                    spread_5m, spread_10m, spread_30m
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (event_id) DO NOTHING
                """,
                (
                    event.event_id,
                    STRATEGY_KEY,
                    event.market_id,
                    event.event_type,
                    event.action,
                    event.action_at,
                    event.price,
                    event.prior_state,
                    event.desired_state,
                    event.reason,
                    event.context_30m,
                    event.spread_5m,
                    event.spread_10m,
                    event.spread_30m,
                ),
            )
        db.execute(
            """
            INSERT INTO pg_v2_autotrader_mtf_shadow_state(
                strategy_key, market_id, state, last_5m_closed_at, last_10m_closed_at,
                last_30m_closed_at, entry_at, entry_price, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, now())
            ON CONFLICT (strategy_key, market_id) DO UPDATE SET
                state=EXCLUDED.state,
                last_5m_closed_at=EXCLUDED.last_5m_closed_at,
                last_10m_closed_at=EXCLUDED.last_10m_closed_at,
                last_30m_closed_at=EXCLUDED.last_30m_closed_at,
                entry_at=EXCLUDED.entry_at,
                entry_price=EXCLUDED.entry_price,
                updated_at=now()
            """,
            (
                STRATEGY_KEY,
                next_value.market_id,
                next_value.state,
                next_value.last_5m_closed_at,
                next_value.last_10m_closed_at,
                next_value.last_30m_closed_at,
                next_value.entry_at,
                next_value.entry_price,
            ),
        )
    return next_value


def evaluate_mtf_entry_shadow_points_v2(
    *,
    market_id: int,
    market_name: str,
    points: Iterable[tuple[str, float]],
    now: datetime | None = None,
) -> tuple[MtfShadowStateV2, tuple[MtfShadowEventV2, ...]]:
    materialized = tuple(points)
    if not materialized:
        raise ValueError("MTF shadow requires canonical history")

    observations: dict[int, tuple[MtfObservationV2, ...]] = {}
    for timeframe in (ENTRY_TIMEFRAME_MINUTES, VALIDATION_TIMEFRAME_MINUTES, REGIME_TIMEFRAME_MINUTES):
        bars = closed_bars_v2(materialized, market=market_name, timeframe_minutes=timeframe)
        items = macd_observations_v2(bars, timeframe_minutes=timeframe)
        if len(items) < 2:
            raise ValueError(f"MTF shadow needs enough closed {timeframe}m bars for MACD 12/26/9")
        observations[timeframe] = items

    state = load_mtf_shadow_state_v2(market_id=market_id, market_name=market_name)
    end = _utc(now or datetime.now(timezone.utc))
    bootstrap_floor = end - timedelta(hours=BOOTSTRAP_BACKFILL_HOURS)
    cursor_by_tf = {
        ENTRY_TIMEFRAME_MINUTES: state.last_5m_closed_at,
        VALIDATION_TIMEFRAME_MINUTES: state.last_10m_closed_at,
        REGIME_TIMEFRAME_MINUTES: state.last_30m_closed_at,
    }

    work: list[tuple[datetime, int, int, MtfObservationV2, MtfObservationV2]] = []
    priority = {REGIME_TIMEFRAME_MINUTES: 0, ENTRY_TIMEFRAME_MINUTES: 1, VALIDATION_TIMEFRAME_MINUTES: 2}
    for timeframe, items in observations.items():
        cursor = cursor_by_tf[timeframe]
        for previous, current in zip(items, items[1:]):
            if current.closed_at > end:
                continue
            if cursor is not None and current.closed_at <= cursor:
                continue
            if cursor is None and current.closed_at < bootstrap_floor:
                continue
            work.append((current.closed_at, priority[timeframe], timeframe, previous, current))
    work.sort(key=lambda item: (item[0], item[1]))

    emitted: list[MtfShadowEventV2] = []
    for _, _, timeframe, previous, current in work:
        previous_30m, latest_30m = _latest_pair_at(observations[REGIME_TIMEFRAME_MINUTES], current.closed_at)
        context_30m = regime_context_30m_v2(previous_30m, latest_30m)
        latest_5m = _latest_at(observations[ENTRY_TIMEFRAME_MINUTES], current.closed_at)
        latest_10m = _latest_at(observations[VALIDATION_TIMEFRAME_MINUTES], current.closed_at)
        decision = decision_for_observation_v2(
            state=state.state,
            timeframe_minutes=timeframe,
            previous=previous,
            current=current,
            context_30m=context_30m,
        )
        event = None
        if decision is not None:
            event = _event_from_decision_v2(
                state=state,
                observation=current,
                decision=decision,
                context_30m=context_30m,
                latest_5m=latest_5m,
                latest_10m=latest_10m,
                latest_30m=latest_30m,
            )
            emitted.append(event)
        state = _persist_progress_v2(state=state, observation=current, event=event)

    return state, tuple(emitted)


def evaluate_market_mtf_entry_shadow_v2(
    *,
    market_id: int,
    market_name: str,
    history_store: MarketHistoryStore,
    now: datetime | None = None,
) -> tuple[MtfShadowStateV2, tuple[MtfShadowEventV2, ...]]:
    end = _utc(now or datetime.now(timezone.utc))
    start = end - timedelta(days=WARMUP_DAYS)
    points = history_store.load_range(market=market_name, start=start, end=end, limit=100_000)
    if not points:
        raise ValueError(f"no canonical history for {market_name}")
    return evaluate_mtf_entry_shadow_points_v2(
        market_id=market_id,
        market_name=market_name,
        points=points,
        now=end,
    )


def run_mtf_entry_shadow_cycle_v2(*, db_path: str = "pricegauger.db") -> MtfShadowCycleSummaryV2:
    ensure_mtf_entry_shadow_schema_v2()
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
            state, events = evaluate_market_mtf_entry_shadow_v2(
                market_id=market_id,
                market_name=market_name,
                history_store=history_store,
            )
            evaluated += 1
            event_count += len(events)
            for event in events:
                LOGGER.info(
                    "MTF shadow market=%s at=%s event=%s action=%s state=%s->%s price=%.5f context30=%s spread5=%s spread10=%s spread30=%s reason=%s",
                    event.market_name,
                    event.action_at.isoformat(),
                    event.event_type,
                    event.action,
                    event.prior_state,
                    event.desired_state,
                    event.price,
                    event.context_30m,
                    event.spread_5m,
                    event.spread_10m,
                    event.spread_30m,
                    event.reason,
                )
            if not events:
                LOGGER.debug("MTF shadow market=%s state=%s no new event", market_name, state.state)
        except Exception as exc:
            failed += 1
            LOGGER.warning("MTF shadow failed market=%s: %s", market_name, exc, exc_info=True)

    return MtfShadowCycleSummaryV2(
        attempted=len(markets),
        evaluated=evaluated,
        events=event_count,
        failed=failed,
    )


def run_mtf_entry_shadow_forever_v2(
    *,
    db_path: str = "pricegauger.db",
    interval_seconds: int = 30,
) -> None:
    interval = max(10, int(interval_seconds))
    ensure_mtf_entry_shadow_schema_v2()
    while True:
        started = time.monotonic()
        try:
            summary = run_mtf_entry_shadow_cycle_v2(db_path=db_path)
            LOGGER.info(
                "MTF shadow cycle attempted=%d evaluated=%d events=%d failed=%d",
                summary.attempted,
                summary.evaluated,
                summary.events,
                summary.failed,
            )
        except Exception as exc:
            LOGGER.exception("MTF shadow cycle failed before market evaluation: %s", exc)
        sleep_to_fixed_start_cadence_v2(started, interval)


__all__ = [
    "ACTION_CONFIRMATION",
    "ACTION_WOULD_BUY",
    "ACTION_WOULD_EXIT",
    "ACTION_WOULD_EXIT_REARM",
    "CONTEXT_BEARISH",
    "CONTEXT_BULLISH",
    "CONTEXT_RECOVERING",
    "CONTEXT_UNKNOWN",
    "ENTRY_TIMEFRAME_MINUTES",
    "EVENT_CONFIRM_10M",
    "EVENT_CONFIRM_30M",
    "EVENT_ENTRY_5M",
    "EVENT_EXIT_30M",
    "EVENT_REJECT_10M",
    "EVENT_REJECT_5M",
    "MtfDecisionV2",
    "MtfObservationV2",
    "MtfShadowEventV2",
    "MtfShadowStateV2",
    "REGIME_TIMEFRAME_MINUTES",
    "STATE_CONFIRMED_30M",
    "STATE_FLAT",
    "STATE_PROVISIONAL_LONG",
    "STATE_VALIDATED_10M",
    "STRATEGY_KEY",
    "VALIDATION_TIMEFRAME_MINUTES",
    "closed_bars_v2",
    "decision_for_observation_v2",
    "evaluate_mtf_entry_shadow_points_v2",
    "macd_observations_v2",
    "regime_context_30m_v2",
    "run_mtf_entry_shadow_cycle_v2",
    "run_mtf_entry_shadow_forever_v2",
]
