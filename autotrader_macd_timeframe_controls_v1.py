from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
from typing import Any

from autotrader_mtf_entry_shadow_v2 import closed_bars_v2, macd_observations_v2
from autotrader_shadow_benchmark_v2 import (
    BENCHMARK_MAX_1M_BARS,
    BENCHMARK_WARMUP_DAYS,
    STATE_FLAT,
    STATE_LONG,
    STATE_SHORT,
    ShadowBenchmarkSeriesV2,
    ShadowEquityPointV2,
    apply_shadow_return_v2,
)
from canonical_market_bars_v2 import CanonicalMarketBarStoreV2, CanonicalMarketBarV2


MACD_CONTROL_TIMEFRAMES_MINUTES_V1 = (2, 5, 10, 15, 20)
MACD_CONTROL_STRATEGY_KEYS_V1 = {
    minutes: f"macd-{minutes}m-flip-control-shadow-v1"
    for minutes in MACD_CONTROL_TIMEFRAMES_MINUTES_V1
}
SERIES_VERSION_V1 = "MACD-TF-12-26-9-v1"


def _utc(value: Any) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def macd_control_strategy_key_v1(timeframe_minutes: int) -> str:
    minutes = int(timeframe_minutes)
    try:
        return MACD_CONTROL_STRATEGY_KEYS_V1[minutes]
    except KeyError as exc:
        raise ValueError(f"unsupported MACD control timeframe: {minutes}m") from exc


def macd_control_strategy_label_v1(timeframe_minutes: int) -> str:
    minutes = int(timeframe_minutes)
    if minutes not in MACD_CONTROL_STRATEGY_KEYS_V1:
        raise ValueError(f"unsupported MACD control timeframe: {minutes}m")
    return f"{minutes}m MACD flip · control"


def _action_at(bar: CanonicalMarketBarV2) -> datetime:
    return _utc(bar.bar_time).replace(second=0, microsecond=0) + timedelta(minutes=1)


def _crosses_by_action_v1(
    bars: tuple[CanonicalMarketBarV2, ...],
    *,
    timeframe_minutes: int,
) -> dict[datetime, str]:
    minutes = int(timeframe_minutes)
    if not bars:
        return {}
    closed = closed_bars_v2(
        tuple(item.point for item in bars),
        market=str(bars[0].market_name),
        timeframe_minutes=minutes,
    )
    observations = macd_observations_v2(closed, timeframe_minutes=minutes)
    crosses: dict[datetime, str] = {}
    for previous, current in zip(observations, observations[1:]):
        # Never invent a cross across missing canonical buckets.
        if current.closed_at - previous.closed_at != timedelta(minutes=minutes):
            continue
        if previous.spread <= 0.0 < current.spread:
            crosses[_utc(current.closed_at)] = STATE_LONG
        elif previous.spread >= 0.0 > current.spread:
            crosses[_utc(current.closed_at)] = STATE_SHORT
    return crosses


def _series_for_timeframe_v1(
    bars: tuple[CanonicalMarketBarV2, ...],
    *,
    timeframe_minutes: int,
    seed_equity: float,
    currency: str,
    started_at: datetime,
    as_of: datetime,
) -> ShadowBenchmarkSeriesV2 | None:
    minutes = int(timeframe_minutes)
    seed = float(seed_equity)
    if minutes not in MACD_CONTROL_STRATEGY_KEYS_V1:
        raise ValueError(f"unsupported MACD control timeframe: {minutes}m")
    if not math.isfinite(seed) or seed <= 0:
        raise ValueError("seed_equity must be finite and positive")
    started = _utc(started_at)
    end = _utc(as_of)
    if end < started:
        raise ValueError("comparison end precedes start")

    price_clock = tuple(
        item
        for item in bars
        if started <= _action_at(item) <= end
    )
    if not price_clock:
        return None

    crosses = _crosses_by_action_v1(bars, timeframe_minutes=minutes)
    state = STATE_FLAT
    equity = seed
    prior_price = float(price_clock[0].close)
    if prior_price <= 0:
        raise ValueError("MACD control price must be positive")
    first_at = _action_at(price_clock[0])
    points = [
        ShadowEquityPointV2(
            closed_at=first_at,
            equity=seed,
            position_state=state,
        )
    ]

    # Start FLAT at the common experiment boundary. Warm-up bars only establish the
    # MACD state; pre-experiment crosses never leak into the baseline position state.
    for item in price_clock[1:]:
        action_at = _action_at(item)
        price = float(item.close)
        if price <= 0:
            raise ValueError("MACD control price must be positive")
        price_return = (price / prior_price) - 1.0
        equity = apply_shadow_return_v2(
            equity=equity,
            position_state=state,
            price_return=price_return,
        )
        if equity <= 0:
            state = STATE_FLAT
        else:
            cross = crosses.get(action_at)
            if cross == STATE_LONG:
                state = STATE_LONG
            elif cross == STATE_SHORT:
                state = STATE_SHORT
        points.append(
            ShadowEquityPointV2(
                closed_at=action_at,
                equity=float(equity),
                position_state=state,
            )
        )
        prior_price = price

    return ShadowBenchmarkSeriesV2(
        strategy_key=macd_control_strategy_key_v1(minutes),
        execution_mode="SHADOW_CONTROL",
        currency=str(currency),
        seed_equity=seed,
        started_at=first_at,
        points=tuple(points),
    )


def load_macd_timeframe_control_series_v1(
    *,
    instrument_id: int,
    seed_equity: float,
    currency: str,
    started_at: datetime,
    as_of: datetime,
    db_path: str = "pricegauger.db",
) -> tuple[ShadowBenchmarkSeriesV2, ...]:
    """Return simple 2/5/10/15/20m MACD 12/26/9 LONG/SHORT baselines.

    All controls use fully closed epoch-aligned bars for their own timeframe and one
    common canonical 1m price clock for mark-to-market comparison. They are read-only
    Strategy Lab controls and have no execution authority.
    """
    started = _utc(started_at)
    end = _utc(as_of)
    bars = CanonicalMarketBarStoreV2(db_path).load_instrument_range(
        instrument_id=int(instrument_id),
        start=started - timedelta(days=BENCHMARK_WARMUP_DAYS),
        end=end,
        limit=BENCHMARK_MAX_1M_BARS,
    )
    if not bars:
        return ()
    series = []
    materialized = tuple(bars)
    for minutes in MACD_CONTROL_TIMEFRAMES_MINUTES_V1:
        item = _series_for_timeframe_v1(
            materialized,
            timeframe_minutes=minutes,
            seed_equity=float(seed_equity),
            currency=str(currency),
            started_at=started,
            as_of=end,
        )
        if item is not None:
            series.append(item)
    return tuple(series)


__all__ = [
    "MACD_CONTROL_STRATEGY_KEYS_V1",
    "MACD_CONTROL_TIMEFRAMES_MINUTES_V1",
    "SERIES_VERSION_V1",
    "load_macd_timeframe_control_series_v1",
    "macd_control_strategy_key_v1",
    "macd_control_strategy_label_v1",
]
