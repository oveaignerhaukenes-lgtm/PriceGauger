from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
import logging
import math
from statistics import median
import time
from typing import Iterable

from autotrader_cadence_v2 import sleep_to_fixed_start_cadence_v2
from autotrader_shadow_benchmark_v2 import ShadowBenchmarkSeriesV2, ShadowEquityPointV2
from canonical_market_bars_v2 import CanonicalMarketBarStoreV2, CanonicalMarketBarV2
from database import connect, using_postgres
from instrument_registry_v2 import list_subscribed_sources_v2
from trading_desk import ChartBar
from trading_desk_indicators import calculate_indicators


LOGGER = logging.getLogger("pricegauger.autotrader.cocktail_mode_1_shadow_v2")

STRATEGY_KEY = "cocktail-mode-1-shadow-v1"
STRATEGY_LABEL = "Cocktail Mode #1"
CONFIG_VERSION = "CM1-2026-09-02-v1"
SOURCE_KIND = "CANONICAL_1M_INTRABAR_MACD"
TIMEFRAMES = (5, 10, 15, 30)
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
WARMUP_DAYS = 10
MAX_1M_BARS = 30_000

POSITION_FLAT = "FLAT"
POSITION_LONG = "LONG"
POSITION_SHORT = "SHORT"
POSITIONS = {POSITION_FLAT, POSITION_LONG, POSITION_SHORT}

MODE_NORMAL = "NORMAL"
MODE_SHOCK = "SHOCK"
MODE_TREND_LOCK = "TREND_LOCK"
MODE_WHIPSAW = "WHIPSAW"
MODES = {MODE_NORMAL, MODE_SHOCK, MODE_TREND_LOCK, MODE_WHIPSAW}

CROSS_UP = "CROSS_UP"
CROSS_DOWN = "CROSS_DOWN"

ACTION_BOOTSTRAP = "BOOTSTRAP_NO_REPLAY"
ACTION_HOLD = "HOLD"
ACTION_FLAT = "FLAT"
ACTION_OPEN_LONG = "OPEN_LONG"
ACTION_OPEN_SHORT = "OPEN_SHORT"
ACTION_FLIP_LONG = "FLIP_LONG"
ACTION_FLIP_SHORT = "FLIP_SHORT"


@dataclass(frozen=True, slots=True)
class CocktailMode1ConfigV1:
    """Explicit first calibration of the adaptive state machine.

    Every threshold is persisted indirectly through CONFIG_VERSION and every feature
    used by a decision is stored per 1m sample. The numbers are hypotheses to measure,
    not claims of optimality.
    """

    max_contiguous_gap_minutes: float = 3.0
    low_activity_range_ratio: float = 0.75
    ambiguous_10m_spread_atr: float = 0.03
    shock_1m_range_ratio: float = 1.50
    shock_activity_z: float = 2.0
    shock_5m_displacement_atr: float = 0.50
    shock_efficiency_5m: float = 0.70
    shock_break_buffer_atr5: float = 0.10
    shock_macd_velocity_atr5: float = 0.03
    trend_lock_macd_velocity_atr30: float = 0.015
    trend_lock_efficiency_30m: float = 0.45
    whipsaw_crosses_30m: int = 3
    whipsaw_efficiency_30m: float = 0.25
    whipsaw_displacement_atr10: float = 0.40
    whipsaw_escape_displacement_atr5: float = 0.50
    whipsaw_escape_break_buffer_atr5: float = 0.15
    support_resistance_lookback_1m: int = 60
    support_resistance_exclude_recent_1m: int = 5
    activity_lookback_1m: int = 60


DEFAULT_CONFIG = CocktailMode1ConfigV1()


@dataclass(frozen=True, slots=True)
class MacdClockV1:
    timeframe_minutes: int
    macd: float
    signal: float
    spread: float
    previous_spread: float
    previous2_spread: float
    velocity_atr: float
    acceleration_atr: float
    cross: str | None
    cross_observed_at: datetime | None
    cross_estimated_at: datetime | None


@dataclass(frozen=True, slots=True)
class CocktailSnapshotV1:
    action_at: datetime
    market_id: int
    instrument_id: int
    market_name: str
    price: float
    clock_5m: MacdClockV1
    clock_10m: MacdClockV1
    clock_15m: MacdClockV1
    clock_30m: MacdClockV1
    atr_5m: float
    atr_10m: float
    atr_30m: float
    range_ratio_1m: float
    activity_z: float
    activity_source: str
    efficiency_5m: float
    efficiency_30m: float
    displacement_5m_atr5: float
    displacement_30m_atr10: float
    support: float | None
    resistance: float | None
    break_direction: str | None
    break_distance_atr5: float
    low_activity: bool
    divergent_5_10: bool
    shock_direction: str | None
    trend_lock_direction: str | None
    whipsaw: bool
    escape_direction: str | None
    recent_fast_crosses_30m: int
    data_gap: bool

    def clock(self, timeframe_minutes: int) -> MacdClockV1:
        mapping = {
            5: self.clock_5m,
            10: self.clock_10m,
            15: self.clock_15m,
            30: self.clock_30m,
        }
        try:
            return mapping[int(timeframe_minutes)]
        except KeyError as exc:
            raise ValueError(f"unsupported Cocktail timeframe: {timeframe_minutes}") from exc


@dataclass(frozen=True, slots=True)
class CocktailStateV1:
    instrument_id: int
    market_id: int
    market_name: str
    position: str = POSITION_FLAT
    mode: str = MODE_NORMAL
    pending_direction: str | None = None
    pending_confirmation_tf: int | None = None
    entry_price: float | None = None
    realized_return_pct: float = 0.0
    transitions: int = 0
    last_sample_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class CocktailDecisionV1:
    action: str
    target_position: str
    mode: str
    pending_direction: str | None
    pending_confirmation_tf: int | None
    reason: str


@dataclass(frozen=True, slots=True)
class CocktailCycleSummaryV1:
    attempted: int
    evaluated: int
    samples: int
    transitions: int
    failed: int


def _utc(value: datetime | str) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _action_at(bar: CanonicalMarketBarV2) -> datetime:
    return _utc(bar.bar_time).replace(second=0, microsecond=0) + timedelta(minutes=1)


def _direction_for_cross(cross: str | None) -> str | None:
    if cross == CROSS_UP:
        return POSITION_LONG
    if cross == CROSS_DOWN:
        return POSITION_SHORT
    return None


def _opposite(direction: str) -> str:
    if direction == POSITION_LONG:
        return POSITION_SHORT
    if direction == POSITION_SHORT:
        return POSITION_LONG
    raise ValueError(f"direction has no opposite: {direction}")


def _sign_direction(value: float, *, epsilon: float = 0.0) -> str | None:
    if value > epsilon:
        return POSITION_LONG
    if value < -epsilon:
        return POSITION_SHORT
    return None


def _bucket_start(stamp: datetime, timeframe_minutes: int) -> datetime:
    value = _utc(stamp)
    minutes = int(timeframe_minutes)
    minute_of_day = value.hour * 60 + value.minute
    bucket_minute = (minute_of_day // minutes) * minutes
    hour, minute = divmod(bucket_minute, 60)
    return value.replace(hour=hour, minute=minute, second=0, microsecond=0)


def _chart_bars_v1(
    bars: Iterable[CanonicalMarketBarV2],
    *,
    timeframe_minutes: int,
) -> tuple[ChartBar, ...]:
    grouped: list[ChartBar] = []
    current_bucket: datetime | None = None
    open_price = high = low = close = 0.0
    volume_total = 0.0
    volume_seen = False
    market = ""

    def append_current() -> None:
        if current_bucket is None:
            return
        grouped.append(
            ChartBar(
                market=market,
                bar_time=current_bucket.isoformat(),
                open=float(open_price),
                high=float(high),
                low=float(low),
                close=float(close),
                volume=float(volume_total) if volume_seen else None,
            )
        )

    for item in bars:
        stamp = _utc(item.bar_time)
        bucket = _bucket_start(stamp, timeframe_minutes)
        market = item.market_name
        if current_bucket is None or bucket != current_bucket:
            append_current()
            current_bucket = bucket
            open_price = float(item.open)
            high = float(item.high)
            low = float(item.low)
            close = float(item.close)
            volume_total = 0.0 if item.volume is None else float(item.volume)
            volume_seen = item.volume is not None
        else:
            high = max(float(high), float(item.high))
            low = min(float(low), float(item.low))
            close = float(item.close)
            if item.volume is not None:
                volume_total += float(item.volume)
                volume_seen = True
    append_current()
    return tuple(grouped)


def _macd_values_v1(
    bars: tuple[CanonicalMarketBarV2, ...],
    *,
    timeframe_minutes: int,
) -> tuple[float, float, float]:
    aggregated = _chart_bars_v1(bars, timeframe_minutes=timeframe_minutes)
    indicators = calculate_indicators(
        aggregated,
        macd_fast=MACD_FAST,
        macd_slow=MACD_SLOW,
        macd_signal=MACD_SIGNAL,
    )
    if not indicators.macd or not indicators.macd_signal:
        raise ValueError(f"Cocktail Mode #1 lacks MACD warmup for {timeframe_minutes}m")
    macd = float(indicators.macd[-1].value)
    signal = float(indicators.macd_signal[-1].value)
    return macd, signal, macd - signal


def _true_ranges_v1(bars: tuple[ChartBar, ...]) -> tuple[float, ...]:
    values: list[float] = []
    previous_close: float | None = None
    for bar in bars:
        high = float(bar.high)
        low = float(bar.low)
        if previous_close is None:
            value = high - low
        else:
            value = max(high - low, abs(high - previous_close), abs(low - previous_close))
        values.append(max(0.0, float(value)))
        previous_close = float(bar.close)
    return tuple(values)


def _atr_v1(bars: tuple[CanonicalMarketBarV2, ...], *, timeframe_minutes: int, period: int = 14) -> float:
    aggregated = _chart_bars_v1(bars, timeframe_minutes=timeframe_minutes)
    ranges = _true_ranges_v1(aggregated)
    if len(ranges) < max(2, period):
        raise ValueError(f"Cocktail Mode #1 lacks ATR warmup for {timeframe_minutes}m")
    tail = ranges[-period:]
    value = sum(tail) / len(tail)
    if value <= 0.0:
        raise ValueError(f"Cocktail Mode #1 invalid {timeframe_minutes}m ATR")
    return float(value)


def _interpolated_cross_at_v1(
    previous_at: datetime,
    current_at: datetime,
    previous_spread: float,
    current_spread: float,
) -> datetime:
    denominator = abs(float(previous_spread)) + abs(float(current_spread))
    fraction = 0.5 if denominator <= 0.0 else abs(float(previous_spread)) / denominator
    seconds = max(0.0, (current_at - previous_at).total_seconds())
    return previous_at + timedelta(seconds=seconds * min(1.0, max(0.0, fraction)))


def _macd_clock_v1(
    bars: tuple[CanonicalMarketBarV2, ...],
    *,
    timeframe_minutes: int,
    atr: float,
    max_gap_minutes: float,
) -> MacdClockV1:
    if len(bars) < 3:
        raise ValueError("Cocktail Mode #1 requires at least three 1m samples")
    macd2, signal2, spread2 = _macd_values_v1(bars[:-2], timeframe_minutes=timeframe_minutes)
    macd1, signal1, spread1 = _macd_values_v1(bars[:-1], timeframe_minutes=timeframe_minutes)
    macd0, signal0, spread0 = _macd_values_v1(bars, timeframe_minutes=timeframe_minutes)
    _ = (macd2, signal2, macd1, signal1)
    current_at = _action_at(bars[-1])
    previous_at = _action_at(bars[-2])
    gap_minutes = (current_at - previous_at).total_seconds() / 60.0
    crossing = None
    if gap_minutes <= float(max_gap_minutes):
        if spread1 <= 0.0 < spread0:
            crossing = CROSS_UP
        elif spread1 >= 0.0 > spread0:
            crossing = CROSS_DOWN
    estimated = None
    if crossing is not None:
        estimated = _interpolated_cross_at_v1(previous_at, current_at, spread1, spread0)
    scale = max(float(atr), 1e-12)
    velocity = (spread0 - spread1) / scale
    acceleration = (spread0 - (2.0 * spread1) + spread2) / scale
    return MacdClockV1(
        timeframe_minutes=int(timeframe_minutes),
        macd=float(macd0),
        signal=float(signal0),
        spread=float(spread0),
        previous_spread=float(spread1),
        previous2_spread=float(spread2),
        velocity_atr=float(velocity),
        acceleration_atr=float(acceleration),
        cross=crossing,
        cross_observed_at=current_at if crossing is not None else None,
        cross_estimated_at=estimated,
    )


def _robust_z_v1(value: float, history: Iterable[float]) -> float:
    materialized = tuple(float(item) for item in history if math.isfinite(float(item)))
    if len(materialized) < 10:
        return 0.0
    center = median(materialized)
    deviations = tuple(abs(item - center) for item in materialized)
    mad = median(deviations)
    if mad <= 1e-12:
        return 0.0
    return float(0.67448975 * (float(value) - center) / mad)


def _efficiency_v1(closes: tuple[float, ...]) -> float:
    if len(closes) < 2:
        return 0.0
    net = abs(float(closes[-1]) - float(closes[0]))
    path = sum(abs(float(current) - float(previous)) for previous, current in zip(closes, closes[1:]))
    if path <= 1e-12:
        return 0.0
    return min(1.0, max(0.0, net / path))


def _support_resistance_v1(
    bars: tuple[CanonicalMarketBarV2, ...],
    *,
    config: CocktailMode1ConfigV1,
) -> tuple[float | None, float | None]:
    exclude = max(1, int(config.support_resistance_exclude_recent_1m))
    lookback = max(20, int(config.support_resistance_lookback_1m))
    if len(bars) < exclude + 20:
        return None, None
    reference = bars[max(0, len(bars) - exclude - lookback): len(bars) - exclude]
    if len(reference) < 20:
        return None, None
    return min(float(item.low) for item in reference), max(float(item.high) for item in reference)


def _break_profile_v1(
    bars: tuple[CanonicalMarketBarV2, ...],
    *,
    support: float | None,
    resistance: float | None,
    atr_5m: float,
    buffer_atr: float,
) -> tuple[str | None, float]:
    if support is None or resistance is None or len(bars) < 2:
        return None, 0.0
    current = float(bars[-1].close)
    previous = float(bars[-2].close)
    buffer = max(0.0, float(buffer_atr)) * float(atr_5m)
    if current > resistance + buffer and previous > resistance + buffer:
        return POSITION_LONG, max(0.0, (current - resistance) / atr_5m)
    if current < support - buffer and previous < support - buffer:
        return POSITION_SHORT, max(0.0, (support - current) / atr_5m)
    return None, 0.0


def _same_direction(a: str | None, b: str | None) -> bool:
    return a is not None and a == b


def build_cocktail_snapshot_v1(
    bars: Iterable[CanonicalMarketBarV2],
    *,
    recent_fast_crosses_30m: int,
    config: CocktailMode1ConfigV1 = DEFAULT_CONFIG,
) -> CocktailSnapshotV1:
    materialized = tuple(bars)
    if len(materialized) < 1_100:
        raise ValueError("Cocktail Mode #1 requires enough canonical 1m history for forming 30m MACD")
    action_at = _action_at(materialized[-1])
    previous_at = _action_at(materialized[-2])
    data_gap = (action_at - previous_at).total_seconds() / 60.0 > float(config.max_contiguous_gap_minutes)

    atr5 = _atr_v1(materialized, timeframe_minutes=5)
    atr10 = _atr_v1(materialized, timeframe_minutes=10)
    atr30 = _atr_v1(materialized, timeframe_minutes=30)
    clocks = {
        timeframe: _macd_clock_v1(
            materialized,
            timeframe_minutes=timeframe,
            atr={5: atr5, 10: atr10, 15: atr10, 30: atr30}[timeframe],
            max_gap_minutes=config.max_contiguous_gap_minutes,
        )
        for timeframe in TIMEFRAMES
    }

    lookback = max(20, int(config.activity_lookback_1m))
    recent = materialized[-(lookback + 1):]
    ranges = tuple(max(0.0, float(item.high) - float(item.low)) for item in recent)
    current_range = ranges[-1]
    history_ranges = ranges[:-1]
    median_range = median(history_ranges) if history_ranges else current_range
    range_ratio = current_range / max(float(median_range), 1e-12)
    range_z = _robust_z_v1(current_range, history_ranges)

    volumes = tuple(float(item.volume) for item in recent[:-1] if item.volume is not None)
    volume_z = None
    if materialized[-1].volume is not None and len(volumes) >= 10:
        volume_z = _robust_z_v1(float(materialized[-1].volume), volumes)
    activity_z = max(range_z, volume_z) if volume_z is not None else range_z
    activity_source = "volume+range" if volume_z is not None else "range_proxy"
    low_activity = range_ratio < float(config.low_activity_range_ratio) and (
        volume_z is None or volume_z < 0.0
    )

    closes5 = tuple(float(item.close) for item in materialized[-6:])
    closes30 = tuple(float(item.close) for item in materialized[-31:])
    efficiency5 = _efficiency_v1(closes5)
    efficiency30 = _efficiency_v1(closes30)
    displacement5 = abs(closes5[-1] - closes5[0]) / atr5
    displacement30 = abs(closes30[-1] - closes30[0]) / atr10

    support, resistance = _support_resistance_v1(materialized, config=config)
    break_direction, break_distance = _break_profile_v1(
        materialized,
        support=support,
        resistance=resistance,
        atr_5m=atr5,
        buffer_atr=config.shock_break_buffer_atr5,
    )

    clock5 = clocks[5]
    clock10 = clocks[10]
    clock15 = clocks[15]
    clock30 = clocks[30]
    sign5 = _sign_direction(clock5.spread)
    ambiguous10 = abs(clock10.spread) / atr10 < float(config.ambiguous_10m_spread_atr)
    sign10 = None if ambiguous10 else _sign_direction(clock10.spread)
    divergent = sign5 is not None and (sign10 is None or sign5 != sign10)

    price_direction = _sign_direction(closes5[-1] - closes5[0])
    macd5_confirmation = (
        _direction_for_cross(clock5.cross) == price_direction
        or (
            _sign_direction(clock5.spread) == price_direction
            and abs(clock5.velocity_atr) >= float(config.shock_macd_velocity_atr5)
        )
    )
    shock_direction = None
    if (
        not data_gap
        and price_direction is not None
        and range_ratio >= float(config.shock_1m_range_ratio)
        and activity_z >= float(config.shock_activity_z)
        and displacement5 >= float(config.shock_5m_displacement_atr)
        and efficiency5 >= float(config.shock_efficiency_5m)
        and break_direction == price_direction
        and macd5_confirmation
    ):
        shock_direction = price_direction

    spread30_direction = _sign_direction(clock30.spread)
    expanding30 = (
        spread30_direction is not None
        and _sign_direction(clock30.previous_spread) == spread30_direction
        and _sign_direction(clock30.previous2_spread) == spread30_direction
        and abs(clock30.spread) > abs(clock30.previous_spread) > abs(clock30.previous2_spread)
    )
    velocity30_direction = _sign_direction(clock30.velocity_atr)
    trend_lock_direction = None
    if (
        not data_gap
        and expanding30
        and velocity30_direction == spread30_direction
        and abs(clock30.velocity_atr) >= float(config.trend_lock_macd_velocity_atr30)
        and efficiency30 >= float(config.trend_lock_efficiency_30m)
    ):
        trend_lock_direction = spread30_direction

    current_fast_crosses = int(clock5.cross is not None) + int(clock10.cross is not None)
    cross_count = int(recent_fast_crosses_30m) + current_fast_crosses
    whipsaw = (
        cross_count >= int(config.whipsaw_crosses_30m)
        and (
            efficiency30 < float(config.whipsaw_efficiency_30m)
            or displacement30 < float(config.whipsaw_displacement_atr10)
        )
    )

    escape_direction = None
    if shock_direction is not None:
        escape_direction = shock_direction
    elif clock30.cross is not None:
        escape_direction = _direction_for_cross(clock30.cross)
    elif break_direction is not None:
        aligned10 = _sign_direction(clock10.spread) == break_direction
        aligned15 = _sign_direction(clock15.spread) == break_direction
        if (
            aligned10
            and aligned15
            and displacement5 >= float(config.whipsaw_escape_displacement_atr5)
            and break_distance >= float(config.whipsaw_escape_break_buffer_atr5)
        ):
            escape_direction = break_direction

    return CocktailSnapshotV1(
        action_at=action_at,
        market_id=int(materialized[-1].market_id),
        instrument_id=int(materialized[-1].instrument_id),
        market_name=str(materialized[-1].market_name),
        price=float(materialized[-1].close),
        clock_5m=clock5,
        clock_10m=clock10,
        clock_15m=clock15,
        clock_30m=clock30,
        atr_5m=float(atr5),
        atr_10m=float(atr10),
        atr_30m=float(atr30),
        range_ratio_1m=float(range_ratio),
        activity_z=float(activity_z),
        activity_source=activity_source,
        efficiency_5m=float(efficiency5),
        efficiency_30m=float(efficiency30),
        displacement_5m_atr5=float(displacement5),
        displacement_30m_atr10=float(displacement30),
        support=support,
        resistance=resistance,
        break_direction=break_direction,
        break_distance_atr5=float(break_distance),
        low_activity=bool(low_activity),
        divergent_5_10=bool(divergent),
        shock_direction=shock_direction,
        trend_lock_direction=trend_lock_direction,
        whipsaw=bool(whipsaw),
        escape_direction=escape_direction,
        recent_fast_crosses_30m=cross_count,
        data_gap=bool(data_gap),
    )


def _target_action_v1(current: str, target: str) -> str:
    if current == target:
        return ACTION_HOLD
    if target == POSITION_FLAT:
        return ACTION_FLAT
    if current == POSITION_FLAT:
        return ACTION_OPEN_LONG if target == POSITION_LONG else ACTION_OPEN_SHORT
    return ACTION_FLIP_LONG if target == POSITION_LONG else ACTION_FLIP_SHORT


def cocktail_mode_1_decision_v1(
    state: CocktailStateV1,
    snapshot: CocktailSnapshotV1,
) -> CocktailDecisionV1:
    """Pure decision contract for Cocktail Mode #1.

    Evidence to exit is intentionally cheaper than evidence to open the opposite side.
    SHOCK is the only fast path that may carry a direct reversal target; a future LIVE
    adapter must still execute that as CLOSE -> confirmed FLAT -> OPEN.
    """
    if state.position not in POSITIONS or state.mode not in MODES:
        raise ValueError("invalid Cocktail Mode #1 state")

    if snapshot.data_gap:
        target = POSITION_FLAT if state.position != POSITION_FLAT else state.position
        return CocktailDecisionV1(
            action=_target_action_v1(state.position, target),
            target_position=target,
            mode=MODE_NORMAL,
            pending_direction=None,
            pending_confirmation_tf=None,
            reason="DATA_GAP_PAUSE: contiguous 1m evidence is missing; do not infer a cross across the gap",
        )

    if state.mode == MODE_WHIPSAW:
        if snapshot.escape_direction is None:
            return CocktailDecisionV1(
                action=_target_action_v1(state.position, POSITION_FLAT),
                target_position=POSITION_FLAT,
                mode=MODE_WHIPSAW,
                pending_direction=None,
                pending_confirmation_tf=None,
                reason="WHIPSAW_PAUSE: remain FLAT until 30m cross or qualified range-break escape",
            )
        target = snapshot.escape_direction
        return CocktailDecisionV1(
            action=_target_action_v1(state.position, target),
            target_position=target,
            mode=MODE_SHOCK if snapshot.shock_direction == target else MODE_NORMAL,
            pending_direction=None,
            pending_confirmation_tf=None,
            reason=f"WHIPSAW_ESCAPE: qualified {target} threshold crossed",
        )

    if snapshot.shock_direction is not None:
        target = snapshot.shock_direction
        return CocktailDecisionV1(
            action=_target_action_v1(state.position, target),
            target_position=target,
            mode=MODE_SHOCK,
            pending_direction=None,
            pending_confirmation_tf=None,
            reason=(
                f"SHOCK_{target}: 1m range/activity + 5m displacement/efficiency + S/R break + 5m MACD confirmation"
            ),
        )

    if snapshot.whipsaw:
        return CocktailDecisionV1(
            action=_target_action_v1(state.position, POSITION_FLAT),
            target_position=POSITION_FLAT,
            mode=MODE_WHIPSAW,
            pending_direction=None,
            pending_confirmation_tf=None,
            reason=(
                f"WHIPSAW_ENTER: {snapshot.recent_fast_crosses_30m} fast crosses/30m with low path efficiency or displacement"
            ),
        )

    trend = snapshot.trend_lock_direction
    if trend is not None and state.position == trend:
        counter = _opposite(trend)
        cross10 = _direction_for_cross(snapshot.clock_10m.cross)
        cross15 = _direction_for_cross(snapshot.clock_15m.cross)
        if cross10 == counter and cross15 == counter:
            return CocktailDecisionV1(
                action=_target_action_v1(state.position, counter),
                target_position=counter,
                mode=MODE_NORMAL,
                pending_direction=None,
                pending_confirmation_tf=None,
                reason=f"TREND_LOCK_RELEASE: 10m and 15m crossed {counter}; reversal confirmed",
            )
        if cross10 == counter:
            return CocktailDecisionV1(
                action=_target_action_v1(state.position, POSITION_FLAT),
                target_position=POSITION_FLAT,
                mode=MODE_TREND_LOCK,
                pending_direction=counter,
                pending_confirmation_tf=15,
                reason=f"TREND_LOCK_EXIT: 10m crossed {counter}; FLAT pending 15m confirmation",
            )
        return CocktailDecisionV1(
            action=ACTION_HOLD,
            target_position=state.position,
            mode=MODE_TREND_LOCK,
            pending_direction=None,
            pending_confirmation_tf=None,
            reason=f"TREND_LOCK_{trend}: strong expanding 30m MACD ignores ordinary 1m/5m counter-noise",
        )

    if state.pending_direction is not None and state.pending_confirmation_tf is not None:
        pending = state.pending_direction
        confirmation = _direction_for_cross(snapshot.clock(state.pending_confirmation_tf).cross)
        if confirmation == pending:
            return CocktailDecisionV1(
                action=_target_action_v1(state.position, pending),
                target_position=pending,
                mode=MODE_NORMAL,
                pending_direction=None,
                pending_confirmation_tf=None,
                reason=f"CONFIRMED_{state.pending_confirmation_tf}M: pending {pending} received cross confirmation",
            )
        cross5 = _direction_for_cross(snapshot.clock_5m.cross)
        if cross5 is not None and cross5 != pending:
            return CocktailDecisionV1(
                action=_target_action_v1(state.position, POSITION_FLAT),
                target_position=POSITION_FLAT,
                mode=MODE_NORMAL,
                pending_direction=None,
                pending_confirmation_tf=None,
                reason=f"PENDING_CANCELLED: 5m crossed back against pending {pending}; stay FLAT",
            )
        return CocktailDecisionV1(
            action=_target_action_v1(state.position, POSITION_FLAT),
            target_position=POSITION_FLAT,
            mode=MODE_NORMAL,
            pending_direction=pending,
            pending_confirmation_tf=state.pending_confirmation_tf,
            reason=f"WAIT_CONFIRMATION: FLAT pending {state.pending_confirmation_tf}m cross toward {pending}",
        )

    if snapshot.low_activity and snapshot.divergent_5_10:
        return CocktailDecisionV1(
            action=_target_action_v1(state.position, POSITION_FLAT),
            target_position=POSITION_FLAT,
            mode=MODE_NORMAL,
            pending_direction=None,
            pending_confirmation_tf=None,
            reason="LOW_ACTIVITY_DIVERGENCE: 5m/10m disagree while activity is weak; pause FLAT",
        )

    cross5 = _direction_for_cross(snapshot.clock_5m.cross)
    if cross5 is not None and cross5 != state.position:
        cross10 = _direction_for_cross(snapshot.clock_10m.cross)
        if cross10 == cross5:
            return CocktailDecisionV1(
                action=_target_action_v1(state.position, cross5),
                target_position=cross5,
                mode=MODE_NORMAL,
                pending_direction=None,
                pending_confirmation_tf=None,
                reason=f"NORMAL_CONFIRMED: 5m and 10m crossed {cross5} on the same canonical 1m clock",
            )
        return CocktailDecisionV1(
            action=_target_action_v1(state.position, POSITION_FLAT),
            target_position=POSITION_FLAT,
            mode=MODE_NORMAL,
            pending_direction=cross5,
            pending_confirmation_tf=10,
            reason=f"NORMAL_5M_TRIGGER: go FLAT and wait for 10m confirmation toward {cross5}",
        )

    return CocktailDecisionV1(
        action=ACTION_HOLD,
        target_position=state.position,
        mode=MODE_NORMAL,
        pending_direction=None,
        pending_confirmation_tf=None,
        reason="NORMAL_HOLD: no qualified cross transition",
    )


def _close_leg_return_pct_v1(state: CocktailStateV1, exit_price: float) -> float:
    if state.position == POSITION_FLAT or state.entry_price is None or state.entry_price <= 0.0:
        return 0.0
    raw = (float(exit_price) / float(state.entry_price)) - 1.0
    return raw * 100.0 if state.position == POSITION_LONG else -raw * 100.0


def apply_cocktail_decision_v1(
    state: CocktailStateV1,
    snapshot: CocktailSnapshotV1,
    decision: CocktailDecisionV1,
) -> CocktailStateV1:
    target = decision.target_position
    if target not in POSITIONS:
        raise ValueError("invalid Cocktail target position")
    realized = float(state.realized_return_pct)
    entry_price = state.entry_price
    transitions = int(state.transitions)
    if target != state.position:
        if state.position != POSITION_FLAT:
            realized += _close_leg_return_pct_v1(state, snapshot.price)
        entry_price = None if target == POSITION_FLAT else float(snapshot.price)
        transitions += 1
    return CocktailStateV1(
        instrument_id=state.instrument_id,
        market_id=state.market_id,
        market_name=state.market_name,
        position=target,
        mode=decision.mode,
        pending_direction=decision.pending_direction,
        pending_confirmation_tf=decision.pending_confirmation_tf,
        entry_price=entry_price,
        realized_return_pct=realized,
        transitions=transitions,
        last_sample_at=snapshot.action_at,
    )


def cocktail_mark_return_pct_v1(state: CocktailStateV1, price: float) -> float:
    return float(state.realized_return_pct) + _close_leg_return_pct_v1(state, float(price))


def ensure_cocktail_mode_1_schema_v1() -> None:
    if not using_postgres():
        raise RuntimeError("Cocktail Mode #1 shadow requires PostgreSQL")
    with connect() as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS pg_v2_autotrader_cocktail_mode_1_state (
                strategy_key TEXT NOT NULL,
                instrument_id BIGINT NOT NULL REFERENCES pg_v2_instruments(instrument_id),
                market_id BIGINT NOT NULL REFERENCES pg_v2_markets(market_id),
                market_name TEXT NOT NULL,
                position TEXT NOT NULL CHECK (position IN ('FLAT','LONG','SHORT')),
                mode TEXT NOT NULL CHECK (mode IN ('NORMAL','SHOCK','TREND_LOCK','WHIPSAW')),
                pending_direction TEXT CHECK (pending_direction IN ('LONG','SHORT')),
                pending_confirmation_tf INTEGER CHECK (pending_confirmation_tf IN (10,15)),
                entry_price DOUBLE PRECISION,
                realized_return_pct DOUBLE PRECISION NOT NULL DEFAULT 0,
                transitions INTEGER NOT NULL DEFAULT 0,
                last_sample_at TIMESTAMPTZ,
                config_version TEXT NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                PRIMARY KEY(strategy_key, instrument_id)
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS pg_v2_autotrader_cocktail_mode_1_samples (
                strategy_key TEXT NOT NULL,
                instrument_id BIGINT NOT NULL REFERENCES pg_v2_instruments(instrument_id),
                market_id BIGINT NOT NULL REFERENCES pg_v2_markets(market_id),
                market_name TEXT NOT NULL,
                action_at TIMESTAMPTZ NOT NULL,
                price DOUBLE PRECISION NOT NULL,
                position_before TEXT NOT NULL,
                position_after TEXT NOT NULL,
                mode_before TEXT NOT NULL,
                mode_after TEXT NOT NULL,
                action TEXT NOT NULL,
                reason TEXT NOT NULL,
                pending_direction TEXT,
                pending_confirmation_tf INTEGER,
                realized_return_pct DOUBLE PRECISION NOT NULL,
                mark_return_pct DOUBLE PRECISION NOT NULL,
                transitions INTEGER NOT NULL,
                cross_5m TEXT,
                cross_5m_estimated_at TIMESTAMPTZ,
                cross_10m TEXT,
                cross_10m_estimated_at TIMESTAMPTZ,
                cross_15m TEXT,
                cross_15m_estimated_at TIMESTAMPTZ,
                cross_30m TEXT,
                cross_30m_estimated_at TIMESTAMPTZ,
                spread_5m DOUBLE PRECISION NOT NULL,
                spread_10m DOUBLE PRECISION NOT NULL,
                spread_15m DOUBLE PRECISION NOT NULL,
                spread_30m DOUBLE PRECISION NOT NULL,
                velocity_5m_atr DOUBLE PRECISION NOT NULL,
                velocity_10m_atr DOUBLE PRECISION NOT NULL,
                velocity_15m_atr DOUBLE PRECISION NOT NULL,
                velocity_30m_atr DOUBLE PRECISION NOT NULL,
                activity_z DOUBLE PRECISION NOT NULL,
                activity_source TEXT NOT NULL,
                range_ratio_1m DOUBLE PRECISION NOT NULL,
                efficiency_5m DOUBLE PRECISION NOT NULL,
                efficiency_30m DOUBLE PRECISION NOT NULL,
                displacement_5m_atr5 DOUBLE PRECISION NOT NULL,
                displacement_30m_atr10 DOUBLE PRECISION NOT NULL,
                support DOUBLE PRECISION,
                resistance DOUBLE PRECISION,
                break_direction TEXT,
                break_distance_atr5 DOUBLE PRECISION NOT NULL,
                shock_direction TEXT,
                trend_lock_direction TEXT,
                whipsaw BOOLEAN NOT NULL,
                escape_direction TEXT,
                recent_fast_crosses_30m INTEGER NOT NULL,
                data_gap BOOLEAN NOT NULL,
                config_version TEXT NOT NULL,
                source_kind TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                PRIMARY KEY(strategy_key, instrument_id, action_at)
            )
            """
        )
        db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_pg_cocktail_samples_instrument_time
            ON pg_v2_autotrader_cocktail_mode_1_samples(instrument_id, action_at DESC)
            """
        )


def load_cocktail_state_v1(*, instrument_id: int, market_id: int, market_name: str) -> CocktailStateV1 | None:
    with connect() as db:
        row = db.execute(
            """
            SELECT position, mode, pending_direction, pending_confirmation_tf,
                   entry_price, realized_return_pct, transitions, last_sample_at
            FROM pg_v2_autotrader_cocktail_mode_1_state
            WHERE strategy_key=? AND instrument_id=?
            """,
            (STRATEGY_KEY, int(instrument_id)),
        ).fetchone()
    if row is None:
        return None
    values = dict(row) if isinstance(row, dict) else {
        "position": row[0], "mode": row[1], "pending_direction": row[2],
        "pending_confirmation_tf": row[3], "entry_price": row[4],
        "realized_return_pct": row[5], "transitions": row[6], "last_sample_at": row[7],
    }
    return CocktailStateV1(
        instrument_id=int(instrument_id),
        market_id=int(market_id),
        market_name=market_name,
        position=str(values["position"]),
        mode=str(values["mode"]),
        pending_direction=None if values.get("pending_direction") is None else str(values["pending_direction"]),
        pending_confirmation_tf=None if values.get("pending_confirmation_tf") is None else int(values["pending_confirmation_tf"]),
        entry_price=None if values.get("entry_price") is None else float(values["entry_price"]),
        realized_return_pct=float(values["realized_return_pct"]),
        transitions=int(values["transitions"]),
        last_sample_at=None if values.get("last_sample_at") is None else _utc(values["last_sample_at"]),
    )


def _recent_fast_cross_count_v1(*, instrument_id: int, action_at: datetime) -> int:
    start = _utc(action_at) - timedelta(minutes=30)
    with connect() as db:
        rows = db.execute(
            """
            SELECT cross_5m, cross_10m
            FROM pg_v2_autotrader_cocktail_mode_1_samples
            WHERE strategy_key=? AND instrument_id=? AND action_at>=? AND action_at<?
            ORDER BY action_at ASC
            """,
            (STRATEGY_KEY, int(instrument_id), start, _utc(action_at)),
        ).fetchall()
    count = 0
    for row in rows:
        values = dict(row) if isinstance(row, dict) else {"cross_5m": row[0], "cross_10m": row[1]}
        count += int(values.get("cross_5m") is not None)
        count += int(values.get("cross_10m") is not None)
    return count


def _persist_sample_and_state_v1(
    *,
    prior: CocktailStateV1,
    snapshot: CocktailSnapshotV1,
    decision: CocktailDecisionV1,
    updated: CocktailStateV1,
) -> None:
    mark = cocktail_mark_return_pct_v1(updated, snapshot.price)
    with connect() as db:
        db.execute(
            """
            INSERT INTO pg_v2_autotrader_cocktail_mode_1_samples(
                strategy_key, instrument_id, market_id, market_name, action_at, price,
                position_before, position_after, mode_before, mode_after, action, reason,
                pending_direction, pending_confirmation_tf, realized_return_pct, mark_return_pct,
                transitions, cross_5m, cross_5m_estimated_at, cross_10m, cross_10m_estimated_at,
                cross_15m, cross_15m_estimated_at, cross_30m, cross_30m_estimated_at,
                spread_5m, spread_10m, spread_15m, spread_30m,
                velocity_5m_atr, velocity_10m_atr, velocity_15m_atr, velocity_30m_atr,
                activity_z, activity_source, range_ratio_1m, efficiency_5m, efficiency_30m,
                displacement_5m_atr5, displacement_30m_atr10, support, resistance,
                break_direction, break_distance_atr5, shock_direction, trend_lock_direction,
                whipsaw, escape_direction, recent_fast_crosses_30m, data_gap,
                config_version, source_kind
            ) VALUES (
                ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?
            )
            ON CONFLICT(strategy_key, instrument_id, action_at) DO NOTHING
            """,
            (
                STRATEGY_KEY, snapshot.instrument_id, snapshot.market_id, snapshot.market_name,
                snapshot.action_at, snapshot.price, prior.position, updated.position, prior.mode,
                updated.mode, decision.action, decision.reason, updated.pending_direction,
                updated.pending_confirmation_tf, updated.realized_return_pct, mark,
                updated.transitions, snapshot.clock_5m.cross, snapshot.clock_5m.cross_estimated_at,
                snapshot.clock_10m.cross, snapshot.clock_10m.cross_estimated_at,
                snapshot.clock_15m.cross, snapshot.clock_15m.cross_estimated_at,
                snapshot.clock_30m.cross, snapshot.clock_30m.cross_estimated_at,
                snapshot.clock_5m.spread, snapshot.clock_10m.spread, snapshot.clock_15m.spread,
                snapshot.clock_30m.spread, snapshot.clock_5m.velocity_atr,
                snapshot.clock_10m.velocity_atr, snapshot.clock_15m.velocity_atr,
                snapshot.clock_30m.velocity_atr, snapshot.activity_z, snapshot.activity_source,
                snapshot.range_ratio_1m, snapshot.efficiency_5m, snapshot.efficiency_30m,
                snapshot.displacement_5m_atr5, snapshot.displacement_30m_atr10,
                snapshot.support, snapshot.resistance, snapshot.break_direction,
                snapshot.break_distance_atr5, snapshot.shock_direction,
                snapshot.trend_lock_direction, snapshot.whipsaw, snapshot.escape_direction,
                snapshot.recent_fast_crosses_30m, snapshot.data_gap, CONFIG_VERSION, SOURCE_KIND,
            ),
        )
        db.execute(
            """
            INSERT INTO pg_v2_autotrader_cocktail_mode_1_state(
                strategy_key, instrument_id, market_id, market_name, position, mode,
                pending_direction, pending_confirmation_tf, entry_price, realized_return_pct,
                transitions, last_sample_at, config_version, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, now())
            ON CONFLICT(strategy_key, instrument_id) DO UPDATE SET
                market_id=EXCLUDED.market_id,
                market_name=EXCLUDED.market_name,
                position=EXCLUDED.position,
                mode=EXCLUDED.mode,
                pending_direction=EXCLUDED.pending_direction,
                pending_confirmation_tf=EXCLUDED.pending_confirmation_tf,
                entry_price=EXCLUDED.entry_price,
                realized_return_pct=EXCLUDED.realized_return_pct,
                transitions=EXCLUDED.transitions,
                last_sample_at=EXCLUDED.last_sample_at,
                config_version=EXCLUDED.config_version,
                updated_at=now()
            """,
            (
                STRATEGY_KEY, updated.instrument_id, updated.market_id, updated.market_name,
                updated.position, updated.mode, updated.pending_direction,
                updated.pending_confirmation_tf, updated.entry_price,
                updated.realized_return_pct, updated.transitions, updated.last_sample_at,
                CONFIG_VERSION,
            ),
        )


def _bootstrap_v1(snapshot: CocktailSnapshotV1) -> CocktailStateV1:
    prior = CocktailStateV1(
        instrument_id=snapshot.instrument_id,
        market_id=snapshot.market_id,
        market_name=snapshot.market_name,
    )
    decision = CocktailDecisionV1(
        action=ACTION_BOOTSTRAP,
        target_position=POSITION_FLAT,
        mode=MODE_NORMAL,
        pending_direction=None,
        pending_confirmation_tf=None,
        reason="BOOTSTRAP_NO_REPLAY: start FLAT on the current canonical 1m clock; historical crosses never create shadow exposure",
    )
    updated = replace(prior, last_sample_at=snapshot.action_at)
    _persist_sample_and_state_v1(prior=prior, snapshot=snapshot, decision=decision, updated=updated)
    return updated


def evaluate_cocktail_instrument_v1(
    *,
    instrument_id: int,
    market_id: int,
    market_name: str,
    bar_store: CanonicalMarketBarStoreV2,
    now: datetime | None = None,
    config: CocktailMode1ConfigV1 = DEFAULT_CONFIG,
) -> tuple[CocktailStateV1, int, int]:
    end = _utc(now or datetime.now(timezone.utc))
    state = load_cocktail_state_v1(
        instrument_id=instrument_id,
        market_id=market_id,
        market_name=market_name,
    )
    start = end - timedelta(days=WARMUP_DAYS)
    bars = bar_store.load_instrument_range(
        instrument_id=int(instrument_id),
        start=start,
        end=end,
        limit=MAX_1M_BARS,
    )
    if len(bars) < 1_100:
        raise ValueError(f"Cocktail Mode #1 lacks canonical warmup for {market_name}")

    if state is None:
        snapshot = build_cocktail_snapshot_v1(
            bars,
            recent_fast_crosses_30m=0,
            config=config,
        )
        return _bootstrap_v1(snapshot), 1, 0

    new_indices = [
        index
        for index, bar in enumerate(bars)
        if _action_at(bar) <= end
        and (state.last_sample_at is None or _action_at(bar) > state.last_sample_at)
    ]
    samples = 0
    transitions = 0
    for index in new_indices:
        if index < 1_099:
            continue
        sample_bars = tuple(bars[: index + 1])
        action_at = _action_at(sample_bars[-1])
        recent_crosses = _recent_fast_cross_count_v1(
            instrument_id=instrument_id,
            action_at=action_at,
        )
        snapshot = build_cocktail_snapshot_v1(
            sample_bars,
            recent_fast_crosses_30m=recent_crosses,
            config=config,
        )
        prior = state
        decision = cocktail_mode_1_decision_v1(prior, snapshot)
        state = apply_cocktail_decision_v1(prior, snapshot, decision)
        _persist_sample_and_state_v1(
            prior=prior,
            snapshot=snapshot,
            decision=decision,
            updated=state,
        )
        samples += 1
        transitioned = state.position != prior.position
        transitions += int(transitioned)
        if transitioned or state.mode != prior.mode or decision.action != ACTION_HOLD:
            LOGGER.info(
                "Cocktail Mode #1 market=%s instrument_id=%d at=%s action=%s position=%s->%s mode=%s->%s pending=%s/%s reason=%s mark_return=%+.4f%% crosses5/10/15/30=%s/%s/%s/%s",
                market_name,
                instrument_id,
                snapshot.action_at.isoformat(),
                decision.action,
                prior.position,
                state.position,
                prior.mode,
                state.mode,
                state.pending_direction,
                state.pending_confirmation_tf,
                decision.reason,
                cocktail_mark_return_pct_v1(state, snapshot.price),
                snapshot.clock_5m.cross,
                snapshot.clock_10m.cross,
                snapshot.clock_15m.cross,
                snapshot.clock_30m.cross,
            )
    return state, samples, transitions


def run_cocktail_mode_1_shadow_cycle_v1(
    *,
    db_path: str = "pricegauger.db",
) -> CocktailCycleSummaryV1:
    ensure_cocktail_mode_1_schema_v1()
    sources = list_subscribed_sources_v2(provider="saxo")
    exact: dict[int, tuple[int, str]] = {}
    for source in sources:
        key = int(source.instrument_id)
        value = (int(source.market_id), str(source.market_name))
        if key in exact and exact[key] != value:
            raise RuntimeError(f"instrument_id {key} resolves to conflicting Cocktail market identity")
        exact[key] = value

    store = CanonicalMarketBarStoreV2(db_path)
    evaluated = samples = transitions = failed = 0
    for instrument_id, (market_id, market_name) in sorted(exact.items()):
        try:
            _, added_samples, added_transitions = evaluate_cocktail_instrument_v1(
                instrument_id=instrument_id,
                market_id=market_id,
                market_name=market_name,
                bar_store=store,
            )
            evaluated += 1
            samples += added_samples
            transitions += added_transitions
        except Exception as exc:
            failed += 1
            LOGGER.warning("Cocktail Mode #1 shadow failed market=%s: %s", market_name, exc, exc_info=True)
    return CocktailCycleSummaryV1(
        attempted=len(exact),
        evaluated=evaluated,
        samples=samples,
        transitions=transitions,
        failed=failed,
    )


def run_cocktail_mode_1_shadow_forever_v1(
    *,
    db_path: str = "pricegauger.db",
    interval_seconds: int = 30,
) -> None:
    interval = max(10, int(interval_seconds))
    ensure_cocktail_mode_1_schema_v1()
    while True:
        started = time.monotonic()
        try:
            summary = run_cocktail_mode_1_shadow_cycle_v1(db_path=db_path)
            LOGGER.info(
                "Cocktail Mode #1 shadow cycle attempted=%d evaluated=%d samples=%d transitions=%d failed=%d",
                summary.attempted,
                summary.evaluated,
                summary.samples,
                summary.transitions,
                summary.failed,
            )
        except Exception as exc:
            LOGGER.exception("Cocktail Mode #1 shadow cycle failed before instrument evaluation: %s", exc)
        sleep_to_fixed_start_cadence_v2(started, interval)


def load_cocktail_shadow_series_v1(
    *,
    instrument_id: int,
    seed_equity: float,
    started_at: datetime,
    as_of: datetime,
) -> ShadowBenchmarkSeriesV2 | None:
    """Expose the accumulated adaptive shadow path to the shared P/L chart.

    The series starts when Cocktail Mode #1 actually began collecting data; it is not
    backfilled with hypothetical pre-deployment trades. Equity is gross/no-spread v1.
    """
    seed = float(seed_equity)
    if seed <= 0:
        raise ValueError("seed_equity must be positive")
    with connect() as db:
        rows = db.execute(
            """
            SELECT action_at, mark_return_pct, position_after
            FROM pg_v2_autotrader_cocktail_mode_1_samples
            WHERE strategy_key=? AND instrument_id=? AND action_at>=? AND action_at<=?
            ORDER BY action_at ASC
            """,
            (STRATEGY_KEY, int(instrument_id), _utc(started_at), _utc(as_of)),
        ).fetchall()
    if not rows:
        return None
    points: list[ShadowEquityPointV2] = []
    for row in rows:
        values = dict(row) if isinstance(row, dict) else {
            "action_at": row[0], "mark_return_pct": row[1], "position_after": row[2]
        }
        equity = seed * (1.0 + (float(values["mark_return_pct"]) / 100.0))
        points.append(
            ShadowEquityPointV2(
                closed_at=_utc(values["action_at"]),
                equity=max(0.0, float(equity)),
                position_state=str(values["position_after"]),
            )
        )
    return ShadowBenchmarkSeriesV2(
        strategy_key=STRATEGY_KEY,
        execution_mode="SHADOW_ADAPTIVE",
        currency="NOK",
        seed_equity=seed,
        started_at=points[0].closed_at,
        points=tuple(points),
    )


__all__ = [
    "ACTION_BOOTSTRAP",
    "ACTION_FLAT",
    "ACTION_FLIP_LONG",
    "ACTION_FLIP_SHORT",
    "ACTION_HOLD",
    "ACTION_OPEN_LONG",
    "ACTION_OPEN_SHORT",
    "CONFIG_VERSION",
    "CocktailDecisionV1",
    "CocktailMode1ConfigV1",
    "CocktailSnapshotV1",
    "CocktailStateV1",
    "CROSS_DOWN",
    "CROSS_UP",
    "DEFAULT_CONFIG",
    "MODE_NORMAL",
    "MODE_SHOCK",
    "MODE_TREND_LOCK",
    "MODE_WHIPSAW",
    "POSITION_FLAT",
    "POSITION_LONG",
    "POSITION_SHORT",
    "SOURCE_KIND",
    "STRATEGY_KEY",
    "STRATEGY_LABEL",
    "apply_cocktail_decision_v1",
    "build_cocktail_snapshot_v1",
    "cocktail_mark_return_pct_v1",
    "cocktail_mode_1_decision_v1",
    "ensure_cocktail_mode_1_schema_v1",
    "evaluate_cocktail_instrument_v1",
    "load_cocktail_shadow_series_v1",
    "run_cocktail_mode_1_shadow_cycle_v1",
    "run_cocktail_mode_1_shadow_forever_v1",
]