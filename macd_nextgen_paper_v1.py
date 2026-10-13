"""NextGen MACD: pure closed-bar target policy and costed PAPER replay.

No broker imports, database writes, execution authority, or LIVE side effects.
The same decide() contract may later be used by a separately reviewed LIVE adapter.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import isfinite
from typing import Sequence

from autotrader_mtf_entry_shadow_v2 import macd_observations_v2
from trading_desk import ChartBar

FAMILY = "MACD"
ENGINE_VERSION = "macd-nextgen-paper-v1"
SUPPORTED_MINUTES = (1, 2, 5, 10, 15, 30)


def _utc(value):
    stamp = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return stamp.replace(tzinfo=timezone.utc) if stamp.tzinfo is None else stamp.astimezone(timezone.utc)


@dataclass(frozen=True)
class MacdConfig:
    minutes: int = 5
    flip: bool = True
    hold_before_flip: bool = True
    pyramide: bool = False
    trailing: bool = False
    max_tranches: int = 5

    def __post_init__(self):
        if self.minutes not in SUPPORTED_MINUTES:
            raise ValueError("unsupported MACD signal timeframe")
        if self.hold_before_flip and self.trailing:
            raise ValueError("Hold before flip and trailing are mutually exclusive")
        if not 1 <= self.max_tranches <= 20:
            raise ValueError("max_tranches must be 1..20")

    @property
    def label(self):
        flags = ["Flip" if self.flip else "Exit-only"]
        if self.hold_before_flip:
            flags.append("Hold")
        if self.pyramide:
            flags.append("Pyramide")
        if self.trailing:
            flags.append("Trailing")
        if not self.hold_before_flip and not self.trailing:
            flags.append("Exit on weakening")
        return "MACD %dm · %s" % (self.minutes, " + ".join(flags))

    @property
    def identity(self):
        return "%s:tf%d:f%d:h%d:p%d:t%d:n%d" % (
            ENGINE_VERSION, self.minutes, self.flip, self.hold_before_flip,
            self.pyramide, self.trailing, self.max_tranches
        )


@dataclass(frozen=True)
class PolicyState:
    target: float = 0.0
    pending_reentry: int = 0


@dataclass(frozen=True)
class Decision:
    state: PolicyState
    reason: str


def decide(config: MacdConfig, state: PolicyState, *, spread: float,
           previous_spread: float | None, contiguous: bool) -> Decision:
    """Pure MACD 12/26/9 position policy.

    Pyramided positions ALWAYS go directly to FLAT on opposite confirmed
    MACD regime. Reentry is separate (next fully closed signal candle),
    never a leveraged reverse order.
    """
    side = (1 if spread > 0 else -1 if spread < 0 else 0)
    old = state.target
    old_side = 1 if old > 0 else -1 if old < 0 else 0
    step = (1.0 / config.max_tranches) if config.pyramide else 1.0
    cross = bool(contiguous and previous_spread is not None and (
        (previous_spread <= 0 < spread) or (previous_spread >= 0 > spread)
    ))
    momentum = None if previous_spread is None else side * (spread - previous_spread)

    # Exit is unconditional: never trail a pyramid down in an opposite MACD regime.
    if old_side and side and old_side != side:
        if config.pyramide:
            return Decision(PolicyState(0.0, side if config.flip else 0),
                            "OPPOSITE_REGIME_FULL_FLAT")
        if config.flip:
            return Decision(PolicyState(float(side), 0), "FLIP_ON_CROSS")
        return Decision(PolicyState(), "OPPOSITE_REGIME_FULL_FLAT")

    if old == 0.0:
        if state.pending_reentry:
            if side == state.pending_reentry and contiguous:
                return Decision(PolicyState(round(side * step, 8)), "REBUILD_AFTER_FLAT")
            return Decision(PolicyState(), "REENTRY_CANCELLED")
        if cross and side:
            return Decision(PolicyState(round(side * step, 8)), "ENTRY_ON_CROSS")
        return Decision(state, "WAIT_FOR_CROSS")

    # No exposure changes from a missing/irregular signal bucket.
    if not contiguous:
        return Decision(state, "WAIT_CONTIGUOUS_SIGNAL")
    if config.pyramide:
        # Growth is conditional on regime-aligned histogram acceleration.
        if momentum is not None and momentum > 0:
            new_size = min(1.0, abs(old) + step)
            return Decision(PolicyState(round(old_side * new_size, 8)), "PYRAMIDE_ADD")
        return Decision(state, "PYRAMIDE_HOLD")

    if config.trailing and momentum is not None:
        if momentum < 0:
            new_size = max(0.0, abs(old) - 1.0 / config.max_tranches)
            return Decision(PolicyState(round(old_side * new_size, 8)), "TRAIL_REDUCE")
        if momentum > 0 and abs(old) < 1:
            new_size = min(1.0, abs(old) + 1.0 / config.max_tranches)
            return Decision(PolicyState(round(old_side * new_size, 8)), "TRAIL_REBUILD")

    if not config.hold_before_flip and not config.trailing and momentum is not None and momentum < 0:
        return Decision(PolicyState(), "WEAKENING_FULL_FLAT")

    return Decision(state, "HOLD")


def _observations(bars: Sequence, minutes: int):
    """Only truly complete consecutive UTC-aligned timeframe buckets can signal."""
    slots = {}
    for bar in sorted(bars, key=lambda x: _utc(x.bar_time)):
        start = _utc(bar.bar_time)
        if start.second or start.microsecond:
            continue
        minute = int(start.timestamp() // 60)
        bucket = minute - (minute % minutes)
        slots.setdefault(bucket, []).append(bar)
    full = []
    for bucket, items in sorted(slots.items()):
        times = [int(_utc(x.bar_time).timestamp() // 60) for x in items]
        if times != list(range(bucket, bucket + minutes)):
            continue
        full.append(ChartBar(market=str(items[0].market_name),
                             bar_time=_utc(items[0].bar_time).isoformat(),
                             open=float(items[0].open), high=max(float(x.high) for x in items),
                             low=min(float(x.low) for x in items), close=float(items[-1].close),
                             volume=None))
    if len(full) < 35:
        return {}
    obs = macd_observations_v2(tuple(full), timeframe_minutes=minutes)
    return {_utc(o.closed_at): o for o in obs}


@dataclass(frozen=True)
class PaperReport:
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


def replay(config: MacdConfig, bars: Sequence, *, started_at,
           costs_enabled: bool = True, commission_side_bps: float = 8.0,
           quoted_spread_bps: float = 1.0) -> PaperReport:
    """Replay with NEXT canonical 1m open fills, no broker or retroactive LIVE P/L.

    Commission is paid once for EACH traded side, quoted full bid/ask spread
    is represented as half spread per traded side. Full reversals cost two
    sides; gross and net results are both recorded.
    """
    if any(not isfinite(float(x)) or float(x) < 0 for x in (commission_side_bps, quoted_spread_bps)):
        raise ValueError("cost assumptions must be finite and nonnegative")
    if not bars:
        return PaperReport(config.identity, config.label, (), 0, 0, 0, 0, 0, 0, (), 0)
    ordered = sorted(bars, key=lambda x: _utc(x.bar_time))
    since = _utc(started_at)
    signals = _observations(ordered, config.minutes)
    decision_state = PolicyState()
    previous_obs = None
    execution_pending = None
    exposure = 0.0
    gross = net = 10000.0
    peak = 10000.0
    executions = orders = completed = 0
    paid = 0.0
    previous_close = None
    points = []
    decisions = []
    observed = set()
    for bar in ordered:
        start = _utc(bar.bar_time)
        end = start + timedelta(minutes=1)
        opening, closing = float(bar.open), float(bar.close)
        if opening <= 0 or closing <= 0:
            continue
        if previous_close and end > since:
            gap_move = opening / previous_close - 1.0
            gross *= max(0, 1.0 + exposure * gap_move)
            net *= max(0, 1.0 + exposure * gap_move)
        if start >= since and execution_pending is not None:
            target, reason, signal_at = execution_pending
            if start >= signal_at and abs(target - exposure) > 1e-10:
                amount = abs(target - exposure)
                # A reversal entails CLOSE and OPEN as separate broker orders.
                orders += 2 if target * exposure < 0 else 1
                executions += 1
                if costs_enabled:
                    bps = commission_side_bps + quoted_spread_bps / 2.0
                    fraction = amount * bps / 10000.0
                    paid += net * fraction
                    net *= max(0, 1.0 - fraction)
                exposure = target
            execution_pending = None
        if end > since:
            move = closing / opening - 1.0
            gross *= max(0, 1.0 + exposure * move)
            net *= max(0, 1.0 + exposure * move)
            peak = max(peak, net)
            # Per-bar peak-drawdown calculated after each move below.
            points.append((end.isoformat(), (net / 10000.0 - 1) * 100,
                           (gross / 10000.0 - 1) * 100))
        previous_close = closing

        ob = signals.get(end)
        if ob is not None and end >= since and end not in observed:
            contiguous = bool(previous_obs and (
                _utc(ob.closed_at) - _utc(previous_obs.closed_at)
                == timedelta(minutes=config.minutes)
            ))
            result = decide(config, decision_state, spread=float(ob.spread),
                            previous_spread=None if previous_obs is None else float(previous_obs.spread),
                            contiguous=contiguous)
            completed += 1
            if abs(result.state.target - decision_state.target) > 1e-10:
                execution_pending = (result.state.target, result.reason, end)
                decisions.append((end.isoformat(), result.reason,
                                  decision_state.target, result.state.target))
            decision_state = result.state
            previous_obs = ob
            observed.add(end)
        elif ob is not None and end < since:
            previous_obs = ob
    # Recompute proper running peak drawdown from marked-to-market net points.
    high, dd = 10000.0, 0.0
    for _, pct, _ in points:
        equity = 10000.0 * (1 + pct / 100.0)
        high = max(high, equity)
        if high:
            dd = max(dd, (1 - equity / high) * 100)
    return PaperReport(config.identity, config.label, tuple(points),
                       (net / 10000.0 - 1) * 100, (gross / 10000.0 - 1) * 100,
                       dd, executions, orders, paid / 10000.0 * 100,
                       tuple(decisions), completed)
