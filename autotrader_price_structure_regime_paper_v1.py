"""PAPER-only structural regime for Tech100; MACD cross is momentum, not trend.

Uses only completed, gap-free 1m price bars. Intended to study whether
blocking *new* countertrend trades in unequivocal multi-hour structures
would have helped. UNKNOWN never blocks a trade in this research model.
No Saxo access, DB writes, LIVE registry or execution authority.
"""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import median

from autotrader_v3_macd_stoch_v21_split_v1 import _completed_bars, _utc


@dataclass(frozen=True, slots=True)
class PriceStructureRegimePaper:
    state: str
    reason: str
    change_4h: float = 0.0
    change_6h: float = 0.0
    noise_points: float = 0.0


@dataclass(frozen=True, slots=True)
class PriceStructureTimelinePaper:
    """Completed 1m structural states; a missing minute expires the last state."""

    closed_at: tuple[datetime, ...]
    states: tuple[str, ...]

    def state_asof(self, at: datetime) -> str:
        stamp = _utc(at)
        index = bisect_right(self.closed_at, stamp) - 1
        if index < 0 or stamp - self.closed_at[index] >= timedelta(minutes=1):
            return "UKJENT"
        return self.states[index]


def _classify_completed_window(recent) -> PriceStructureRegimePaper:
    """Called only for 361 exact, gap-free and completed price observations."""
    close = [float(row.close) for row in recent]
    true_ranges = [max(b.high-b.low,
                       abs(b.high-a.close),abs(b.low-a.close))
                   for a,b in zip(recent[-61:-1],recent[-60:])]
    typical = median(true_ranges)
    if typical <= 0:
        return PriceStructureRegimePaper("UKJENT", "No positive observed true range")
    change_4h = close[-1] - close[-241]
    change_6h = close[-1] - close[0]
    prev2h, last2h = recent[-241:-121], recent[-121:]
    earlier_average = sum(close[-120:-60])/60
    recent_average = sum(close[-60:])/60
    two_hour_average = sum(close[-120:])/120

    bearish = (
        change_4h <= -8*typical and change_6h <= -12*typical
        and max(b.high for b in last2h) < max(b.high for b in prev2h)
        and min(b.low for b in last2h) < min(b.low for b in prev2h)
        and recent_average < earlier_average and close[-1] < two_hour_average
    )
    bullish = (
        change_4h >= 8*typical and change_6h >= 12*typical
        and max(b.high for b in last2h) > max(b.high for b in prev2h)
        and min(b.low for b in last2h) > min(b.low for b in prev2h)
        and recent_average > earlier_average and close[-1] > two_hour_average
    )
    state = "BEAR" if bearish else "BULL" if bullish else "UKJENT"
    return PriceStructureRegimePaper(
        state,"Four independent completed-price confirmations" if state!="UKJENT"
        else "No unambiguous multi-hour direction",
        round(change_4h,4),round(change_6h,4),round(typical,4),
    )


def price_structure_regime_paper(*, source_bars, cutoff,
                                  market_name: str) -> PriceStructureRegimePaper:
    """Four predeclared price-only confirmations; opposite momentum is allowed.

    1. 4h displacement at least 8x typical 1m true range;
    2. 6h displacement at least 12x typical 1m true range;
    3. highs AND lows of the latest 2h below (or above) prior 2h;
    4. latest 60m average below (or above) previous 60m and price below
       (or above) latest 120m average.
    All four must agree; otherwise UNKNOWN, to avoid blocking doubtful cases.
    These are PAPER hypotheses, not validated/tuned trading thresholds.
    """
    rows = _completed_bars(source_bars, timeframe=1,
                           cutoff=cutoff, market=market_name)
    recent = rows[-361:]
    if len(recent) != 361 or any(
        _utc(b.bar_time) - _utc(a.bar_time) != timedelta(minutes=1)
        for a, b in zip(recent, recent[1:])
    ):
        return PriceStructureRegimePaper("UKJENT", "Less than 6h gap-free completed 1m bars")
    return _classify_completed_window(recent)


def price_structure_timeline_from_closed_1m_paper(*, source_bars, cutoff,
                                                   market_name: str) -> PriceStructureTimelinePaper:
    """Build once per minute, then use O(log n) historical regime lookups per BBO.

    This timeline is descriptive only: it never blocks the Impulse Catcher.
    """
    rows = _completed_bars(source_bars, timeframe=1,
                           cutoff=cutoff, market=market_name)
    stamps, states = [], []
    consecutive = 0
    previous = None
    for index, bar in enumerate(rows):
        stamp = _utc(bar.bar_time)
        consecutive = consecutive + 1 if previous is not None and (
            stamp-previous == timedelta(minutes=1)) else 1
        previous = stamp
        stamps.append(stamp+timedelta(minutes=1))
        states.append(_classify_completed_window(rows[index-360:index+1]).state
                      if consecutive >= 361 else "UKJENT")
    return PriceStructureTimelinePaper(tuple(stamps), tuple(states))


def structural_entry_allowed_paper(*, side: str, regime: PriceStructureRegimePaper) -> bool:
    """Countertrend entry veto only; never veto an exit or emergency close."""
    if side not in ("LONG", "SHORT"):
        raise ValueError("Only one-sided LONG/SHORT PAPER entries supported")
    return not ((side == "LONG" and regime.state == "BEAR") or
                (side == "SHORT" and regime.state == "BULL"))
