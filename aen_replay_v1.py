"""AEn Core: deterministic, BROKER-FREE historical PAPER replay.

Only completed contiguous candles are used. Structure pivots become actionable
AFTER right-side confirmation. Orders fill at the next available canonical 1m
open (a model, NOT actual Saxo latency or spread). No DB or broker imports.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import isfinite
from typing import Sequence

from aen_core_v1 import AEnConfig, Bar, Inventory, StructureEvent, confirmed_structure_events, evaluate_structure

FAMILIES = ("MACD Hold", "MACD Histogram", "MACD Hysteresis", "MACD + Stochastic")
TIMEFRAMES = (1, 2, 5, 10, 15, 30)
ENGINE_VERSION = "aen-paper-v1"
START_EQUITY = 10000.0


def utc(stamp):
    dt = stamp if isinstance(stamp, datetime) else datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


@dataclass(frozen=True)
class AEnPaperConfig:
    family: str = "MACD Hold"
    minutes: int = 5
    structure_minutes: int = 5
    pivot_left: int = 2
    pivot_right: int = 2
    max_units: int = 1
    adaptive: bool = False
    structure_scaling: bool = True
    confirmation_ladder: bool = False
    pulse_min_pct: float = 0.12
    impulse_enabled: bool = False
    impulse_pct: float = 0.3
    volume_factor: float = 1.4
    retrace_wait_bars: int = 3
    hard_adverse_pct: float = 0.5
    hysteresis_ratio: float = 0.5
    dwell_minutes: int = 20
    unit_exposure: float = 0.2
    costs_enabled: bool = True
    commission_side_bps: float = 8.0
    quoted_spread_bps: float = 1.0

    def __post_init__(self):
        AEnConfig(self.minutes, self.structure_minutes, self.pivot_left,
                  self.pivot_right, self.max_units)
        if self.family not in FAMILIES:
            raise ValueError("unsupported AEn strategy")
        vals = (self.pulse_min_pct, self.impulse_pct, self.volume_factor, self.hard_adverse_pct,
                self.hysteresis_ratio, self.unit_exposure,
                self.commission_side_bps, self.quoted_spread_bps)
        if any(not isfinite(float(v)) or v < 0 for v in vals):
            raise ValueError("invalid AEn parameter")
        if not 0 < self.unit_exposure <= 1 or self.max_units * self.unit_exposure > 20:
            raise ValueError("invalid research notional sizing")
        if not 0 < self.volume_factor or not 0 <= self.hysteresis_ratio <= 10:
            raise ValueError("invalid impulse / hysteresis")
        if not 1 <= self.retrace_wait_bars <= 60 or self.dwell_minutes < 1:
            raise ValueError("invalid cooldown")

    @property
    def identity(self):
        # Complete parameter identity ensures UI never merges mismatched curves.
        return (f"{ENGINE_VERSION}:{self.family}:m{self.minutes}:s{self.structure_minutes}"
                f":p{self.pivot_left}-{self.pivot_right}:n{self.max_units}:a{int(self.adaptive)}"
                f":sc{int(self.structure_scaling)}:lad{int(self.confirmation_ladder)}:pulse{self.pulse_min_pct}:im{int(self.impulse_enabled)}"
                f":ip{self.impulse_pct}:vf{self.volume_factor}:wait{self.retrace_wait_bars}"
                f":stop{self.hard_adverse_pct}:h{self.hysteresis_ratio}"
                f":dw{self.dwell_minutes}:unit{self.unit_exposure}:c{int(self.costs_enabled)}"
                f":fee{self.commission_side_bps}:sp{self.quoted_spread_bps}")

    @property
    def label(self):
        return f"AEn {self.family} · {self.minutes}m{' AUTO' if self.adaptive else ''}"


@dataclass(frozen=True)
class Candle:
    end: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float | None


@dataclass(frozen=True)
class Indicator:
    end: datetime
    histogram: float
    previous_histogram: float
    stoch_k: float | None
    stoch_d: float | None


@dataclass(frozen=True)
class AEnReport:
    identity: str
    label: str
    points: tuple
    return_pct: float
    gross_pct: float
    max_drawdown_pct: float
    executions: int
    estimated_broker_orders: int
    total_cost_pct: float
    decisions: tuple
    completed_signal_bars: int
    fills: tuple
    timeframe_changes: tuple
    turnover_units: int


def _aggregate(bars: Sequence, minutes: int) -> tuple[Candle, ...]:
    if minutes not in TIMEFRAMES:
        raise ValueError("unsupported timeframe")
    buckets: dict[int, list] = {}
    for bar in sorted(bars, key=lambda b: utc(b.bar_time)):
        start = utc(bar.bar_time)
        if start.second or start.microsecond:
            continue
        minute = int(start.timestamp() // 60)
        buckets.setdefault(minute - minute % minutes, []).append(bar)
    result = []
    for first, rows in sorted(buckets.items()):
        starts = [int(utc(b.bar_time).timestamp() // 60) for b in rows]
        if starts != list(range(first, first + minutes)):
            continue
        first_open = float(rows[0].open)
        high = max(float(b.high) for b in rows)
        low = min(float(b.low) for b in rows)
        close = float(rows[-1].close)
        if any(not isfinite(x) for x in (first_open, high, low, close)):
            continue
        if first_open <= 0 or low <= 0 or not low <= close <= high:
            continue
        volumes = [getattr(b, "volume", None) for b in rows]
        volume = (sum(float(v) for v in volumes)
                  if all(v is not None and isfinite(float(v)) and float(v) >= 0 for v in volumes)
                  else None)
        result.append(Candle(datetime.fromtimestamp((first + minutes) * 60, tz=timezone.utc),
                             first_open, high, low, close, volume))
    return tuple(result)


def _ema(prices: list[float], span: int) -> list[float]:
    if not prices:
        return []
    factor = 2.0 / (span + 1)
    values = [prices[0]]
    for price in prices[1:]:
        values.append(factor * price + (1 - factor) * values[-1])
    return values


def _indicators(candles: Sequence[Candle]) -> dict[datetime, Indicator]:
    closes = [b.close for b in candles]
    fast, slow = _ema(closes, 12), _ema(closes, 26)
    hist_base = [a - b for a, b in zip(fast, slow)]
    signal = _ema(hist_base, 9)
    hist = [m - s for m, s in zip(hist_base, signal)]
    k_values: list[float | None] = []
    for i, bar in enumerate(candles):
        if i < 13:
            k_values.append(None)
            continue
        window = candles[i - 13:i + 1]
        lo, hi = min(x.low for x in window), max(x.high for x in window)
        k_values.append(50.0 if hi == lo else 100.0 * (bar.close - lo) / (hi - lo))
    results = {}
    for i, bar in enumerate(candles):
        if i < 35:
            continue
        last3 = k_values[i - 2:i + 1]
        d = sum(last3) / 3 if all(x is not None for x in last3) else None
        results[bar.end] = Indicator(bar.end, hist[i], hist[i - 1], k_values[i], d)
    return results


def _structure(candles: Sequence[Candle], config: AEnPaperConfig) -> dict[datetime, tuple[StructureEvent, ...]]:
    """Split irregular candles into contiguous segments; never bridge market gaps."""
    grouped: dict[datetime, list[StructureEvent]] = {}
    run: list[Candle] = []
    segment_start = 0
    def flush():
        if not run:
            return
        converted = [Bar(x.end.isoformat(), x.high, x.low, x.close) for x in run]
        cfg = AEnConfig(config.minutes, config.structure_minutes,
                        config.pivot_left, config.pivot_right, config.max_units)
        for event in confirmed_structure_events(converted, cfg):
            unique = StructureEvent(event.kind, segment_start + event.pivot_index,
                                    segment_start + event.known_index, event.level)
            grouped.setdefault(run[event.known_index].end, []).append(unique)
    for candle in candles:
        if run and candle.end - run[-1].end != timedelta(minutes=config.structure_minutes):
            flush()
            segment_start += len(run)
            run = []
        run.append(candle)
    flush()
    return {key: tuple(value) for key, value in grouped.items()}


def _desired_regime(config: AEnPaperConfig, indicator: Indicator) -> str:
    h, p = indicator.histogram, indicator.previous_histogram
    if config.family == "MACD Histogram":
        delta = h - p
        return "LONG" if delta > 0 else "SHORT" if delta < 0 else "HOLD"
    if config.family == "MACD Hysteresis":
        if abs(h) < abs(p) * config.hysteresis_ratio:
            return "HOLD"
    if config.family == "MACD + Stochastic":
        if indicator.stoch_d is None or indicator.stoch_k is None:
            return "HOLD"
        if h > 0 and indicator.stoch_k > indicator.stoch_d:
            return "LONG"
        if h < 0 and indicator.stoch_k < indicator.stoch_d:
            return "SHORT"
        return "HOLD"
    return "LONG" if h > 0 else "SHORT" if h < 0 else "HOLD"


def _propose(current: int, indicator: Indicator, *, cooling_count: int,
             strength_count: int) -> int:
    idx = TIMEFRAMES.index(current)
    if cooling_count >= 2 and idx > 0:
        return TIMEFRAMES[idx - 1]
    if strength_count >= 2 and idx < len(TIMEFRAMES) - 1:
        return TIMEFRAMES[idx + 1]
    return current


def replay(config: AEnPaperConfig, bars: Sequence, *, started_at) -> AEnReport:
    ordered = sorted(bars, key=lambda b: utc(b.bar_time))
    since = utc(started_at)
    if not ordered:
        return AEnReport(config.identity, config.label, (), 0, 0, 0, 0, 0, 0, (), 0, (), (), 0)
    minute_bars = _aggregate(ordered, 1)
    # Strict enough for a canonical feed; gaps never create artificial signal bars.
    indicator_sets = {tf: _indicators(_aggregate(ordered, tf)) for tf in TIMEFRAMES}
    structure_events = _structure(_aggregate(ordered, config.structure_minutes), config)
    signal_tf = config.minutes
    latest_indicators: dict[int, Indicator] = {}
    inventory = Inventory()
    pending = None
    arm = "HOLD"
    protected_level = None
    previous_close = None
    active_break = False
    last_switch = None
    cooling_count = strength_count = 0
    impulse_watch = None
    gross = net = peak = START_EQUITY
    points, decisions, fills, switches = [], [], [], []
    executions = orders = completed = turnover = 0
    total_cost = 0.0
    last_decision_at = None
    ladder_level = 0

    for minute_index, bar in enumerate(minute_bars):
        end = bar.end
        start = end - timedelta(minutes=1)
        if bar.open <= 0 or bar.close <= 0:
            continue
        units_before = inventory.units * (1 if inventory.side == "LONG" else -1 if inventory.side == "SHORT" else 0)
        exposure = units_before * config.unit_exposure
        if previous_close is not None and end > since:
            gap = bar.open / previous_close - 1
            gross *= max(0.0, 1 + exposure * gap)
            net *= max(0.0, 1 + exposure * gap)
        if start >= since and pending is not None and start >= pending[2]:
            target, reason, requested_at, pending_tf = pending
            old_units = units_before
            new_units = target.units * (1 if target.side == "LONG" else -1 if target.side == "SHORT" else 0)
            if old_units != new_units:
                quantity = abs(new_units - old_units)
                # Flat-first means this model never creates a single netting reversal.
                if old_units * new_units < 0:
                    raise RuntimeError("unsafe direct reversal requested")
                orders += 1
                executions += 1
                turnover += quantity
                if config.costs_enabled:
                    fee = (config.commission_side_bps + config.quoted_spread_bps / 2) / 10000
                    fraction = quantity * config.unit_exposure * fee
                    amount = net * fraction
                    total_cost += amount
                    net *= max(0, 1 - fraction)
                inventory = target
                if inventory.side == "HOLD":
                    protected_level = None
                    active_break = False
                    impulse_watch = None
                    ladder_level = 0
                elif old_units == 0:
                    protected_level = None
                    active_break = False
                    impulse_watch = None
                    ladder_level = 1 if reason == "PULSE_1M_PROBE" else 0
                elif reason == "PULSE_2M_CONFIRM":
                    ladder_level = 2
                elif reason == "PULSE_5M_CONFIRM":
                    ladder_level = 5
                fills.append((start.isoformat(), new_units, reason, pending_tf, bar.open))
            pending = None
        units = inventory.units * (1 if inventory.side == "LONG" else -1 if inventory.side == "SHORT" else 0)
        exposure = units * config.unit_exposure
        if end > since:
            movement = bar.close / bar.open - 1
            gross *= max(0.0, 1 + exposure * movement)
            net *= max(0.0, 1 + exposure * movement)
            peak = max(peak, net)
            points.append((end.isoformat(), (net / START_EQUITY - 1) * 100,
                           (gross / START_EQUITY - 1) * 100, units))
        previous_close = bar.close

        for tf in TIMEFRAMES:
            observed = indicator_sets[tf].get(end)
            if observed is not None:
                latest_indicators[tf] = observed
        obs = latest_indicators.get(signal_tf)
        fresh_signal = obs is not None and obs.end == end
        if fresh_signal:
            completed += 1

        if end < since or pending is not None:
            continue

        # AEn's auto-controller only adjusts timeframe, with explicit dwell.
        # The switch bar is suppressed for trading; no order can be caused by a switch.
        if config.adaptive and fresh_signal and obs is not None:
            decelerating = obs.histogram * (obs.histogram - obs.previous_histogram) < 0
            accelerating = obs.histogram * (obs.histogram - obs.previous_histogram) > 0
            cooling_count = cooling_count + 1 if decelerating else 0
            strength_count = strength_count + 1 if accelerating else 0
            proposed = _propose(signal_tf, obs, cooling_count=cooling_count,
                                strength_count=strength_count)
            if proposed != signal_tf and (last_switch is None or
                                          end - last_switch >= timedelta(minutes=config.dwell_minutes)):
                switches.append((end.isoformat(), signal_tf, proposed,
                                 "cooling" if cooling_count >= 2 else "strengthening"))
                signal_tf, last_switch = proposed, end
                cooling_count = strength_count = 0
                continue

        regime = _desired_regime(config, obs) if obs is not None else "HOLD"
        if obs is None or end - obs.end > timedelta(minutes=max(2, signal_tf * 2)):
            regime = "HOLD"
        # Never trade on the same bar as an adaptive resolution change.
        if last_switch == end:
            continue

        def enqueue(target: Inventory, reason: str):
            nonlocal pending, last_decision_at
            if pending is not None or target == inventory:
                return
            old = inventory.units * (1 if inventory.side == "LONG" else -1 if inventory.side == "SHORT" else 0)
            new = target.units * (1 if target.side == "LONG" else -1 if target.side == "SHORT" else 0)
            if old * new < 0:
                raise RuntimeError("AEn must be flat before reversing")
            pending = (target, reason, end, signal_tf)
            decisions.append((end.isoformat(), reason, old, new, signal_tf))
            last_decision_at = end

        # Hard cap reduction always wins, even when indicators are missing.
        if inventory.units > config.max_units:
            enqueue(Inventory(inventory.side, config.max_units,
                              inventory.structure_break, inventory.last_add_event),
                    "MAX_UNITS_REDUCE")
            continue

        # Impulse warning/exit: candle against current position, with reliable
        # rising real volume. Missing/weak volume => bounded retrace wait.
        if inventory.side != "HOLD" and config.impulse_enabled:
            is_against = (bar.close < bar.open if inventory.side == "LONG"
                          else bar.close > bar.open)
            if is_against and abs(bar.close / bar.open - 1) * 100 >= config.impulse_pct:
                recent = [x.volume for x in minute_bars[max(0, minute_index - 10):minute_index]
                          if x.volume is not None]
                high_volume = (bar.volume is not None and len(recent) >= 5 and
                               sum(recent) > 0 and bar.volume >=
                               (sum(recent) / len(recent)) * config.volume_factor)
                if high_volume:
                    enqueue(Inventory(), "IMPULSE_VOLUME_EXIT")
                    impulse_watch = None
                    continue
                if impulse_watch is None:
                    impulse_watch = (end, bar.open, bar.close, inventory.side)
            if impulse_watch is not None:
                begun, first_price, shock_close, watched_side = impulse_watch
                if watched_side != inventory.side:
                    impulse_watch = None
                else:
                    shock = abs(first_price - shock_close)
                    recovery = (bar.close >= shock_close + 0.5 * shock
                                if watched_side == "LONG" else bar.close <= shock_close - 0.5 * shock)
                    worse = (bar.close <= shock_close * (1 - config.hard_adverse_pct / 100)
                             if watched_side == "LONG"
                             else bar.close >= shock_close * (1 + config.hard_adverse_pct / 100))
                    expired = end - begun >= timedelta(minutes=config.retrace_wait_bars)
                    if recovery or worse or expired:
                        enqueue(Inventory(), "IMPULSE_RETRACE_EXIT" if recovery else
                                "IMPULSE_STOP_EXIT" if worse else "IMPULSE_TIMEOUT_EXIT")
                        impulse_watch = None
                        continue

        events = structure_events.get(end, ())
        for event in events:
            if event.kind == "HH":
                arm = "LONG"
                active_break = False if inventory.side == "HOLD" else active_break
                if inventory.side == "SHORT" and not active_break:
                    active_break = True
                    if inventory.units > 1:
                        enqueue(Inventory("SHORT", inventory.units - 1, True,
                                          inventory.last_add_event), "STRUCTURE_HH_REDUCE")
            elif event.kind == "LL":
                arm = "SHORT"
                if inventory.side == "LONG" and not active_break:
                    active_break = True
                    if inventory.units > 1:
                        enqueue(Inventory("LONG", inventory.units - 1, True,
                                          inventory.last_add_event), "STRUCTURE_LL_REDUCE")
            if pending is not None:
                break
            # Upon opposite pivot following structure break exit wholly.
            if inventory.side == "LONG" and active_break and event.kind == "LH":
                enqueue(Inventory(), "STRUCTURE_LH_FLAT")
            elif inventory.side == "SHORT" and active_break and event.kind == "HL":
                enqueue(Inventory(), "STRUCTURE_HL_FLAT")
            elif event.kind == "HL" and arm == "LONG" and regime == "LONG":
                if inventory.side == "HOLD":
                    enqueue(Inventory("LONG", 1, False, event.known_index),
                            "HH_HL_OPEN")
                elif inventory.side == "LONG" and not active_break and config.structure_scaling:
                    result = evaluate_structure(inventory, event=event,
                                                cfg=AEnConfig(config.minutes,config.structure_minutes,
                                                              config.pivot_left,config.pivot_right,
                                                              config.max_units),regime="LONG")
                    if result.action == "ADD":
                        enqueue(result.target, "HH_HL_ADD")
                protected_level = event.level
            elif event.kind == "LH" and arm == "SHORT" and regime == "SHORT":
                if inventory.side == "HOLD":
                    enqueue(Inventory("SHORT", 1, False, event.known_index),
                            "LL_LH_OPEN")
                elif inventory.side == "SHORT" and not active_break and config.structure_scaling:
                    result = evaluate_structure(inventory, event=event,
                                                cfg=AEnConfig(config.minutes,config.structure_minutes,
                                                              config.pivot_left,config.pivot_right,
                                                              config.max_units),regime="SHORT")
                    if result.action == "ADD":
                        enqueue(result.target, "LL_LH_ADD")
                protected_level = event.level
            if pending is not None:
                break

        # Optional causally ordered 1m -> 2m -> 5m confirmation ladder.
        # A probe uses ONE unit only. Confirmation can add ONE unit per step;
        # further exposure is earned by confirmed structure HL/LH events.
        if config.confirmation_ladder and pending is None:
            fast = indicator_sets[1].get(end)
            slow2 = indicator_sets[2].get(end)
            slow5 = indicator_sets[5].get(end)
            if inventory.side == "HOLD" and fast is not None:
                direction = ("LONG" if fast.histogram > 0 > fast.previous_histogram
                             else "SHORT" if fast.histogram < 0 < fast.previous_histogram
                             else "HOLD")
                candle_matches = (direction == "LONG" and bar.close > bar.open or
                                  direction == "SHORT" and bar.close < bar.open)
                pulse = abs(bar.close / bar.open - 1) * 100 >= config.pulse_min_pct
                main_cooling = (obs is not None and
                                obs.histogram * (obs.histogram - obs.previous_histogram) < 0)
                if direction != "HOLD" and candle_matches and pulse and (
                        arm == direction or main_cooling):
                    enqueue(Inventory(direction,1,False,-1), "PULSE_1M_PROBE")
            elif inventory.side != "HOLD" and ladder_level == 1 and slow2 is not None:
                aligned = ((slow2.histogram > 0 and inventory.side == "LONG") or
                           (slow2.histogram < 0 and inventory.side == "SHORT"))
                if aligned and inventory.units < config.max_units:
                    enqueue(Inventory(inventory.side, inventory.units + 1,
                                      inventory.structure_break, inventory.last_add_event),
                            "PULSE_2M_CONFIRM")
            elif inventory.side != "HOLD" and ladder_level == 2 and slow5 is not None:
                aligned = ((slow5.histogram > 0 and inventory.side == "LONG") or
                           (slow5.histogram < 0 and inventory.side == "SHORT"))
                if aligned and inventory.units < config.max_units:
                    enqueue(Inventory(inventory.side, inventory.units + 1,
                                      inventory.structure_break, inventory.last_add_event),
                            "PULSE_5M_CONFIRM")

        # Last protected HL/LH breaches are checked at completed bar close.
        if pending is None and inventory.side != "HOLD" and protected_level is not None:
            breach = (bar.close < protected_level if inventory.side == "LONG" else
                      bar.close > protected_level)
            if breach and not active_break:
                active_break = True
                if inventory.units == 1:
                    enqueue(Inventory(), "PROTECTED_SWING_FLAT")
                else:
                    enqueue(Inventory(inventory.side, inventory.units - 1, True,
                                      inventory.last_add_event), "PROTECTED_SWING_REDUCE")

        # A confirmed MACD reversal closes exposure, NEVER opens the other side.
        if pending is None and inventory.side != "HOLD" and fresh_signal and regime in ("LONG", "SHORT"):
            if regime != inventory.side:
                enqueue(Inventory(), "MACD_REVERSE_FLAT")

    high = START_EQUITY
    dd = 0.0
    for _, pct, _, _ in points:
        balance = START_EQUITY * (1 + pct / 100)
        high = max(high, balance)
        if high > 0:
            dd = max(dd, (1 - balance / high) * 100)
    return AEnReport(config.identity, config.label, tuple(points),
                     (net / START_EQUITY - 1) * 100,
                     (gross / START_EQUITY - 1) * 100, dd,
                     executions, orders, total_cost / START_EQUITY * 100,
                     tuple(decisions), completed, tuple(fills),
                     tuple(switches), turnover)
