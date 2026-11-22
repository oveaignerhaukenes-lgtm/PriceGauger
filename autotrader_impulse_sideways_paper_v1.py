"""PAPER: impulse entries specialized for established sideways movement.

The regime is inferred from *completed*, gap-free 1m prices. Entry vetoes
never touch an existing position or its safety exits. No Saxo HTTP, PG writes,
LIVE strategy registration or retrospective signal classification.
"""
from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from math import isfinite
from statistics import median

from autotrader_impulse_catcher_profiles_v1 import impulse_catcher_config
from autotrader_impulse_catcher_replay_v1 import ImpulseQuote
from autotrader_impulse_catcher_v1 import ImpulseCatcherConfig, ImpulseCatcherDecision
from autotrader_impulse_v14_chop_paper_v1 import ImpulseChopGatePaper
from autotrader_v3_macd_stoch_v21_split_v1 import _completed_bars, _utc

SIDEWAYS = "SIDEWAYS_CONFIRMED"
TREND_BULL = "TREND_BULL"
TREND_BEAR = "TREND_BEAR"
TRANSITION = "TRANSITION"
UNKNOWN = "UNKNOWN"
PAPER_MODES = ("sideways_only", "sideways_plus_shock")


@dataclass(frozen=True, slots=True)
class SidewaysContextPaper:
    state: str = UNKNOWN
    reason: str = "INSUFFICIENT_COMPLETED_BARS"
    efficiency_30: float | None = None
    reversals_30: int = 0


@dataclass(frozen=True, slots=True)
class SidewaysTimelinePaper:
    available_at: tuple[datetime, ...]
    states: tuple[SidewaysContextPaper, ...]

    def state_asof(self, at: datetime) -> SidewaysContextPaper:
        stamp = _utc(at)
        pos = bisect_right(self.available_at, stamp) - 1
        if pos < 0 or stamp - self.available_at[pos] >= timedelta(minutes=1):
            return SidewaysContextPaper(reason="STALE_OR_MISSING_1M")
        return self.states[pos]


def _path_state(closes: tuple[float, ...], *, minutes: int) -> tuple[str, float, int]:
    moves = tuple(b-a for a,b in zip(closes,closes[1:]))
    if len(moves) != minutes:
        raise ValueError("exact 30m or 60m required")
    travel = sum(abs(x) for x in moves)
    if travel <= 1e-9:
        return UNKNOWN, 0., 0
    net = sum(moves)
    efficiency = abs(net) / travel
    noise = median(abs(x) for x in moves)
    deadband = max(0.1, 0.2 * noise)
    directions = [1 if x > 0 else -1 for x in moves if abs(x) >= deadband]
    reversals = sum(a != b for a,b in zip(directions,directions[1:]))
    width = max(closes) - min(closes)
    if (efficiency <= (0.22 if minutes == 30 else 0.25)
        and reversals >= (7 if minutes == 30 else 12)
        and width >= 10. and travel >= 5 * width):
        return SIDEWAYS, efficiency, reversals
    if efficiency >= (0.45 if minutes == 30 else 0.35):
        return TREND_BULL if net > 0 else TREND_BEAR, efficiency, reversals
    return UNKNOWN, efficiency, reversals


def classify_sideways_context_paper(bars) -> SidewaysContextPaper:
    """Same exact market instrument and contiguous finished minutes only."""
    rows = tuple(bars)[-61:]
    if len(rows) < 31:
        return SidewaysContextPaper()
    try:
        stamps = tuple(_utc(b.bar_time) for b in rows)
        if any(t.second or t.microsecond for t in stamps) or any(
            b-a != timedelta(minutes=1) for a,b in zip(stamps,stamps[1:])
        ):
            return SidewaysContextPaper(reason="GAPPED_1M")
        closes = tuple(float(b.close) for b in rows)
        if not all(isfinite(x) and x > 0 for x in closes):
            return SidewaysContextPaper(reason="INVALID_1M")
    except (ValueError, TypeError, AttributeError):
        return SidewaysContextPaper(reason="INVALID_1M")
    recent, eff, reversals = _path_state(closes[-31:], minutes=30)
    if len(closes) < 61:
        return SidewaysContextPaper(recent if recent == SIDEWAYS else UNKNOWN,
                                     "30M_PROVISIONAL", round(eff,4), reversals)
    longer, _, _ = _path_state(closes[-61:], minutes=60)
    if recent in (TREND_BULL, TREND_BEAR) and longer in (
        TREND_BULL, TREND_BEAR) and recent != longer:
        return SidewaysContextPaper(TRANSITION,"OPPOSING_30M_60M",round(eff,4),reversals)
    if recent == SIDEWAYS and longer == SIDEWAYS:
        return SidewaysContextPaper(SIDEWAYS,"BOTH_WINDOWS_RANGE",round(eff,4),reversals)
    if longer in (TREND_BULL, TREND_BEAR):
        return SidewaysContextPaper(longer,"60M_TREND",round(eff,4),reversals)
    if recent in (TREND_BULL, TREND_BEAR):
        return SidewaysContextPaper(TRANSITION,"30M_EMERGING_TREND",round(eff,4),reversals)
    return SidewaysContextPaper(UNKNOWN,"UNCONFIRMED_30M_60M",round(eff,4),reversals)


def sideways_timeline_paper(*, source_bars, cutoff: datetime,
                             market_name: str) -> SidewaysTimelinePaper:
    completed = _completed_bars(source_bars, timeframe=1,
                                cutoff=cutoff, market=market_name)
    timestamps, observations = [], []
    for index, bar in enumerate(completed):
        block = completed[max(0,index-60):index+1]
        timestamps.append(_utc(bar.bar_time)+timedelta(minutes=1))
        observations.append(classify_sideways_context_paper(block))
    return SidewaysTimelinePaper(tuple(timestamps), tuple(observations))


def specialized_ic_config_paper(side: str) -> ImpulseCatcherConfig:
    """Fewer, stronger impulses; more patient normal exits; explicit PAPER only."""
    base = impulse_catcher_config(side, "1.3")
    return replace(base,
        min_impulse_points=15.,relative_impulse_multiple=4.5,
        minimum_directional_efficiency=0.86,
        exhaustion_seconds=11.,minimum_retrace_points=5.,
        retrace_fraction=0.30,urgent_retrace_points=18.,
        cooldown_seconds=25.,exit_noise_multiple=5.,
        exit_confirmation_seconds=4.,
    )


@dataclass(frozen=True, slots=True)
class SidewaysEntryVerdictPaper:
    allowed: bool
    state: str
    reason: str


class SpecializedICEntryGatePaper:
    def __init__(self, *, quotes: tuple[ImpulseQuote, ...],
                 config: ImpulseCatcherConfig, timeline: SidewaysTimelinePaper,
                 mode: str):
        if mode not in PAPER_MODES:
            raise ValueError("Unsupported PAPER impulse specialization")
        self.quotes = tuple(quotes)
        self.times = tuple(q.at for q in quotes)
        self.config = config
        self.timeline = timeline
        self.mode = mode
        self.chop = ImpulseChopGatePaper(self.quotes, config)

    def _clear_opposite_shock(self, decision: ImpulseCatcherDecision, state: str) -> bool:
        # Strong WITH-trend impulses belong to the existing regime strategy.
        if not ((state == TREND_BULL and self.config.side == "SHORT") or
                (state == TREND_BEAR and self.config.side == "LONG")):
            return False
        if (decision.window_seconds != 3 or
            decision.trigger_points < max(30., 6. * decision.baseline_points)):
            return False
        prior_end = decision.at-timedelta(seconds=decision.window_seconds)
        start = bisect_left(self.times,prior_end-timedelta(seconds=60))
        end = bisect_left(self.times,prior_end)
        previous = self.quotes[start:end]
        if len(previous) < 30 or (
            previous[-1].at-previous[0].at).total_seconds() < 45 or any(
                not 0 < (b.at-a.at).total_seconds() <= self.config.quote_gap_seconds
                for a,b in zip(previous,previous[1:])):
            return False
        mids = tuple(q.mid for q in previous)
        if self.config.side == "LONG":
            return decision.price >= max(mids)+2.
        return decision.price <= min(mids)-2.

    def evaluate(self, decision: ImpulseCatcherDecision) -> SidewaysEntryVerdictPaper:
        if decision.target != self.config.side:
            raise ValueError("Only matching entry decisions can be gated")
        context = self.timeline.state_asof(decision.at)
        if context.state == SIDEWAYS:
            chop_verdict = self.chop.evaluate(decision)
            return SidewaysEntryVerdictPaper(
                chop_verdict.allowed, context.state,
                "SIDEWAYS_IMPULSE" if chop_verdict.allowed else "SIDEWAYS_CHOP_TRAP")
        if (self.mode == "sideways_plus_shock" and self._clear_opposite_shock(
            decision, context.state)):
            return SidewaysEntryVerdictPaper(True,context.state,"EXCEPTIONAL_COUNTER_SHOCK")
        return SidewaysEntryVerdictPaper(False,context.state,"NOT_CONFIRMED_SIDEWAYS")


__all__ = ["SIDEWAYS", "TREND_BULL", "TREND_BEAR", "TRANSITION", "UNKNOWN",
           "PAPER_MODES", "SidewaysContextPaper", "SidewaysTimelinePaper",
           "classify_sideways_context_paper", "sideways_timeline_paper",
           "specialized_ic_config_paper", "SpecializedICEntryGatePaper"]
