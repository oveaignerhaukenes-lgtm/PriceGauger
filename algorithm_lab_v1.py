"""Algorithm Lab v1: causal, read-only directional PAPER research engine.

Only validated declarative plans run. Never eval/exec AI-written Python, import
strategy files, access Saxo execution, or write production trading tables.
30m MACD uses fully complete, contiguous 30m buckets of canonical 1m OHLC.
Signals decided at minute CLOSE fill no earlier than NEXT observed minute OPEN.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, replace
from datetime import datetime, timedelta, timezone
from math import isfinite
from typing import Sequence

MAX_BARS = 12000
PRESETS = {
    "Trend Long / Flat": {"kind": "trend", "side": "long", "regime_rule": "spread",
                          "lookback": 3, "entry_bps": 3., "exit_bps": 3.,
                          "fade_bps": 0., "max_hold": 180},
    "Trend Short / Flat": {"kind": "trend", "side": "short", "regime_rule": "spread",
                           "lookback": 3, "entry_bps": 3., "exit_bps": 3.,
                           "fade_bps": 0., "max_hold": 180},
    "Impulse Up Collector": {"kind": "impulse", "side": "long", "regime_rule": "none",
                              "lookback": 1, "entry_bps": 8., "exit_bps": 4.,
                              "fade_bps": 1., "max_hold": 5},
    "Impulse Down Collector": {"kind": "impulse", "side": "short", "regime_rule": "none",
                                "lookback": 1, "entry_bps": 8., "exit_bps": 4.,
                                "fade_bps": 1., "max_hold": 5},
}
ALLOWED_KEYS = frozenset(next(iter(PRESETS.values())))
ALLOWED_KINDS = frozenset(("trend", "impulse"))
ALLOWED_SIDES = frozenset(("long", "short"))
ALLOWED_REGIMES = frozenset(("none", "spread", "slope", "both"))


def validate_plan(raw: dict) -> dict:
    """No arbitrary code, SQL, fields, or LIVE capability in a model plan."""
    if not isinstance(raw, dict) or set(raw) != ALLOWED_KEYS:
        raise ValueError("Algoritmen må ha nøyaktig de tillatte planfeltene.")
    if raw["kind"] not in ALLOWED_KINDS or raw["side"] not in ALLOWED_SIDES:
        raise ValueError("Ukjent strategi eller retning.")
    if raw["regime_rule"] not in ALLOWED_REGIMES:
        raise ValueError("Ukjent regimeregel.")
    if raw["kind"] == "trend" and raw["regime_rule"] == "none":
        raise ValueError("Trendstrategier krever 30m-regime.")
    for key in ("lookback", "max_hold"):
        value = raw[key]
        if type(value) is not int or not 1 <= value <= (30 if key == "lookback" else 240):
            raise ValueError(f"{key} må være et heltall innenfor grensene.")
    for key in ("entry_bps", "exit_bps", "fade_bps"):
        value = raw[key]
        if type(value) not in (int, float) or not isfinite(value) or not 0 <= value <= 500:
            raise ValueError(f"{key} må være et endelig tall fra 0 til 500 bp.")
    if raw["entry_bps"] <= 0:
        raise ValueError("Inngangsgrensen må være positiv.")
    return dict(raw)


@dataclass(frozen=True)
class LabCosts:
    point_value_nok: float = 100.0
    starting_nav_nok: float = 10000.0
    lot_size: float = .01
    spread_bps: float = 2.0
    slippage_bps: float = 1.0
    commission_nok: float = 0.0
    variable_fee_bps: float = 0.0

    def __post_init__(self):
        for k, v in asdict(self).items():
            if not isfinite(float(v)) or v < 0:
                raise ValueError(f"Ugyldig kostnad: {k}")
            if k in ("point_value_nok", "starting_nav_nok", "lot_size") and v <= 0:
                raise ValueError(f"{k} må være positiv.")

    def execution_cost(self, price: float, lots: float) -> float:
        return abs(lots) * price * self.point_value_nok * (
            self.spread_bps / 20000 + self.slippage_bps / 10000
            + self.variable_fee_bps / 10000
        ) + self.commission_nok


@dataclass(frozen=True)
class LabPoint:
    at: datetime
    close: float
    nav_nok: float
    position: float
    signal: str
    regime: str


@dataclass(frozen=True)
class LabTrade:
    at: datetime
    action: str
    price: float
    before: float
    after: float
    cost_nok: float
    reason: str


@dataclass(frozen=True)
class LabResult:
    points: tuple[LabPoint, ...]
    trades: tuple[LabTrade, ...]
    pnl_nok: float
    return_pct: float
    drawdown_pct: float
    total_cost_nok: float
    gaps: int
    warmup_30m_bars: int
    source_bars: int


def utc(stamp) -> datetime:
    at = stamp if isinstance(stamp, datetime) else datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    if at.tzinfo is None:
        raise ValueError("Tidsstempel må ha tidssone.")
    return at.astimezone(timezone.utc)


class _Macd30:
    def __init__(self):
        self.n = 0
        self.fast = self.slow = self.signal = 0.
        self.previous_hist = None
        self.hist = None
        self.spread = None

    def update(self, close: float):
        if self.n == 0:
            self.fast = self.slow = close
            self.signal = 0.
        else:
            self.fast += (2 / 13) * (close - self.fast)
            self.slow += (2 / 27) * (close - self.slow)
            macd = self.fast - self.slow
            self.signal += (2 / 10) * (macd - self.signal)
        self.n += 1
        # Do not claim 30m regime until 35 complete 30m bars have closed.
        if self.n >= 35:
            self.previous_hist = self.hist
            macd = self.fast - self.slow
            self.spread = macd - self.signal
            self.hist = self.spread

    def side(self, rule: str) -> int:
        if self.spread is None:
            return 0
        spread_side = 1 if self.spread > 0 else -1 if self.spread < 0 else 0
        slope_side = (1 if self.previous_hist is not None and
                      self.spread > self.previous_hist else
                      -1 if self.previous_hist is not None and
                      self.spread < self.previous_hist else 0)
        if rule == "spread":
            return spread_side
        if rule == "slope":
            return slope_side
        if rule == "both" and spread_side == slope_side:
            return spread_side
        return 0


def replay_algorithm(*, plan: dict, bars: Sequence, costs: LabCosts,
                     start_at, end_at) -> LabResult:
    """Deterministic PAPER; one legal positive-sized position or FLAT only.

    A gap ends the current segment. No invented gap returns, missing-bar fills,
    future pivots, future 30m candles, intraminute executions or broker fills.
    """
    p = validate_plan(plan)
    start, end = utc(start_at), utc(end_at)
    if end <= start:
        raise ValueError("Slutt må være etter start.")
    if len(bars) > MAX_BARS:
        raise ValueError(f"Maks {MAX_BARS} ettminuttsbarer per kjøring.")
    rows = sorted(bars, key=lambda b: utc(b.bar_time))
    if not rows:
        raise ValueError("Ingen 1m-historikk tilgjengelig.")
    previous = None
    for bar in rows:
        t = utc(bar.bar_time)
        vals = (float(bar.open), float(bar.high), float(bar.low), float(bar.close))
        if (t.second or t.microsecond or (previous is not None and t <= previous)
                or not all(isfinite(x) and x > 0 for x in vals)
                or vals[1] < max(vals[0], vals[3]) or vals[2] > min(vals[0], vals[3])):
            raise ValueError("Historikken inneholder ugyldige 1m-prisbarer.")
        previous = t

    nav = peak = costs.starting_nav_nok
    position = 0.
    pending = None
    entry_index = None
    total_cost = 0.
    max_drawdown = 0.
    gaps = 0
    trades = []
    points = []
    prices = []
    macd = _Macd30()
    bucket = []
    last_time = None
    last_close = None
    side = 1 if p["side"] == "long" else -1
    latest_index = 0
    for bar in rows:
        at = utc(bar.bar_time)
        closed = at + timedelta(minutes=1)
        op, close = float(bar.open), float(bar.close)
        if last_time is not None and at - last_time != timedelta(minutes=1):
            gaps += 1
            if position:
                charge = costs.execution_cost(last_close, position)
                nav -= charge
                total_cost += charge
                trades.append(LabTrade(last_time + timedelta(minutes=1),
                                       "GAP_FLAT", last_close, position, 0., charge,
                                       "Paper flat ved siste kjente close; ikke faktisk gap-fill"))
            position = 0.
            pending = None
            entry_index = None
            prices = []
            bucket = []
            macd = _Macd30()
            last_close = None
        if at >= end:
            break
        if at >= start:
            if last_close is not None and position:
                nav += position * (op - last_close) * costs.point_value_nok
            if pending is not None:
                target, why = pending
                if target != position:
                    charge = costs.execution_cost(op, target - position)
                    nav -= charge
                    total_cost += charge
                    trades.append(LabTrade(at, "OPEN" if target else "FLAT",
                                           op, position, target, charge, why))
                    position = target
                    entry_index = latest_index if target else None
                pending = None
            if position:
                nav += position * (close - op) * costs.point_value_nok
            if nav <= 0:
                raise ValueError("PAPER-kapitalen er oppbrukt med valgte eksponeringsantakelser.")
        elif position:
            raise AssertionError("Ingen posisjon tillatt før målevinduet")
        last_close = close
        last_time = at
        prices.append(close)

        # A 30m state updates only at the end of a full uninterrupted bucket.
        bucket_start = at.replace(minute=(at.minute // 30) * 30, second=0, microsecond=0)
        if not bucket or bucket[0][0] != bucket_start:
            bucket = []
        bucket.append((bucket_start, at, close))
        if closed.minute % 30 == 0 and len(bucket) == 30 and (
                bucket[0][1] == closed - timedelta(minutes=30)):
            macd.update(close)
            bucket = []

        signal = "WARMUP"
        regime = ("UNKNOWN" if macd.side(p["regime_rule"]) == 0
                  else "UP" if macd.side(p["regime_rule"]) > 0 else "DOWN")
        if closed >= start and closed <= end:
            latest_index += 1
            if len(prices) > p["lookback"]:
                momentum = side * (close / prices[-1 - p["lookback"]] - 1.) * 10000
                allowed = (p["kind"] == "impulse" and p["regime_rule"] == "none") or (
                    macd.side(p["regime_rule"]) == side)
                if position:
                    held = latest_index - entry_index if entry_index is not None else 0
                    if (not allowed or momentum <= -p["exit_bps"]
                            or (p["kind"] == "impulse" and momentum < p["fade_bps"])
                            or held >= p["max_hold"]):
                        pending = (0., "EXIT regime / momentum / utmattelse / maks hold")
                        signal = "EXIT"
                    else:
                        signal = "HOLD"
                elif allowed and momentum >= p["entry_bps"]:
                    pending = (side * costs.lot_size, "ENTRY bekreftet close, neste 1m open")
                    signal = "ENTRY"
                else:
                    signal = "FLAT"
            if nav <= 0:
                raise ValueError("Ugyldig netto PAPER-kapital.")
            peak = max(peak, nav)
            max_drawdown = max(max_drawdown, 100 * (peak - nav) / peak)
            points.append(LabPoint(closed, close, nav, position, signal, regime))

    if not points:
        raise ValueError("Ingen fullførte 1m-barer i valgt målevindu.")
    if position:
        price = points[-1].close
        charge = costs.execution_cost(price, position)
        nav -= charge
        total_cost += charge
        trades.append(LabTrade(points[-1].at, "END_FLAT", price, position, 0., charge,
                               "Beregnet sluttlikvidering ved siste close, ikke reell fill"))
        points[-1] = replace(points[-1], nav_nok=nav, position=0.,
                             signal="END_FLAT")
        max_drawdown = max(max_drawdown, 100 * (peak - nav) / peak)
    return LabResult(tuple(points), tuple(trades), nav - costs.starting_nav_nok,
                     100 * (nav / costs.starting_nav_nok - 1.), max_drawdown,
                     total_cost, gaps, macd.n, len(rows))
