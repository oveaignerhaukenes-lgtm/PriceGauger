"""PAPER-only Impulse Catcher v1.4 hypothesis: avoid obvious range-chop traps.

This gate evaluates only the observed 60 seconds BEFORE the qualifying
impulse's 3s/10s trigger window. It never vetoes an exit, a clear range
breakout, an unknown window, or a trade merely because of a bearish regime.
Nothing here is registered in LIVE or fetches new Saxo data.
"""
from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
from datetime import timedelta

from autotrader_impulse_catcher_replay_v1 import ImpulseQuote
from autotrader_impulse_catcher_v1 import ImpulseCatcherConfig, ImpulseCatcherDecision


@dataclass(frozen=True, slots=True)
class ChopGateVerdictPaper:
    allowed: bool
    reason: str
    previous_efficiency: float | None = None
    previous_range_points: float | None = None
    reversals: int = 0


def _significant_swings(prices: tuple[float, ...], threshold: float) -> int:
    """Causal zig-zag reversal count, with no intrabar interpolation."""
    if len(prices)<2 or threshold<=0:
        return 0
    anchor=extreme=prices[0]
    direction=0
    reversals=0
    for price in prices[1:]:
        if direction==0:
            if price-anchor>=threshold:
                direction=1
                extreme=price
            elif anchor-price>=threshold:
                direction=-1
                extreme=price
        elif direction==1:
            extreme=max(extreme,price)
            if extreme-price>=threshold:
                reversals+=1
                direction=-1
                extreme=price
        else:
            extreme=min(extreme,price)
            if price-extreme>=threshold:
                reversals+=1
                direction=1
                extreme=price
    return reversals


class ImpulseChopGatePaper:
    """Read-only, as-of quote lookup for strict evidence of futile range-chop."""

    def __init__(self, quotes: tuple[ImpulseQuote, ...], config: ImpulseCatcherConfig):
        self.quotes=quotes
        self.times=tuple(q.at for q in quotes)
        self.config=config

    def evaluate(self, decision: ImpulseCatcherDecision) -> ChopGateVerdictPaper:
        if decision.target != self.config.side:
            raise ValueError("PAPER chop guard only evaluates matching entry decisions")
        if decision.window_seconds not in self.config.windows_seconds:
            return ChopGateVerdictPaper(True,"UKJENT_TRIGGER_WINDOW")
        prior_end=decision.at-timedelta(seconds=decision.window_seconds)
        end=bisect_left(self.times,prior_end)
        start=bisect_left(self.times,prior_end-timedelta(seconds=60))
        window=self.quotes[start:end]
        if len(window)<30 or (window[-1].at-window[0].at).total_seconds()<45:
            return ChopGateVerdictPaper(True,"UKJENT_PRIOR_WINDOW")
        # Refuse to infer a market state across a gap or duplicate timestamp.
        if any(not 0<(b.at-a.at).total_seconds()<=self.config.quote_gap_seconds
               for a,b in zip(window,window[1:])):
            return ChopGateVerdictPaper(True,"UKJENT_PRIOR_WINDOW")
        prices=tuple(q.mid for q in window)
        path=sum(abs(b-a) for a,b in zip(prices,prices[1:]))
        if path<=0:
            return ChopGateVerdictPaper(True,"UKJENT_NO_PRICE_PATH")
        efficiency=abs(prices[-1]-prices[0])/path
        width=max(prices)-min(prices)
        reversals=_significant_swings(
            prices,max(2.,0.5*self.config.min_impulse_points))
        # An unmistakable breakout must pass, even out of a choppy backdrop.
        margin=max(1.5,0.08*width)
        outside=(decision.price>=max(prices)-margin
                 if self.config.side=="LONG"
                 else decision.price<=min(prices)+margin)
        trap=(
            efficiency<=.20 and width>=2.5*self.config.min_impulse_points
            and reversals>=4 and not outside
            and decision.trigger_points<=.55*width
        )
        return ChopGateVerdictPaper(
            not trap,"RANGE_CHOP_TRAP" if trap else "ALLOW_NOT_PROVEN_TRAP",
            round(efficiency,4),round(width,4),reversals,
        )
