"""Causal price-shape -> future PAPER strategy-return gate research.

Every feature uses only COMPLETED historical 1m candles at decision time t.
Label uses PAPER NAV between t and t+30m; it is NOT known at t. No gate
may be configured from holdout results. A 30m purge separates train and
holdout. "Skipped return" is a proxy, not a full FLAT-replay or realized
saving: an actual gate must pay exit/re-entry costs and alter strategy state.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime,timedelta,timezone
from math import isfinite
from statistics import mean
from typing import Sequence

from autotrader_v3_session_loss_lab_v1 import classify_completed_regime,utc


@dataclass(frozen=True)
class GateWindow:
    decision_at:datetime
    future_until:datetime
    class_key:str
    regime:str
    price_efficiency:float
    completed_turns:int
    median_swing_bps:float|None
    range_bps:float
    spread_bps:float
    future_paper_nav_pct:float


@dataclass(frozen=True)
class GateEvaluation:
    train_windows:int
    test_windows:int
    purged_windows:int
    abstained_windows:int
    train_cutoff:datetime
    trained_actions:tuple[tuple[str,str,int,float],...]
    holdout_baseline_sum_pct:float
    holdout_only_allowed_sum_pct:float
    holdout_skipped_positive_sum_pct:float
    holdout_skipped_negative_sum_pct:float
    holdout_predicted_trade_windows:int
    warning:str


@dataclass(frozen=True)
class GateFullReplayComparison:
    """True PAPER state evolution, not a sum of foregone 30m returns."""
    cutoff:datetime
    baseline_holdout_pct:float
    gated_holdout_pct:float
    gated_minus_baseline_pct:float
    baseline_orders:int
    gated_orders:int
    baseline_cost_nok:float
    gated_cost_nok:float
    baseline_max_drawdown_pct:float
    gated_max_drawdown_pct:float
    cost_source:str
    warning:str


def gate_class_for_completed_bars_v1(bars:Sequence,spread_bps:float)->str|None:
    """Assign the same shape used in training from exactly 30 prior 1m bars."""
    if len(bars)!=30 or not isfinite(spread_bps) or spread_bps<0:
        return None
    stamps=[utc(b.bar_time) for b in bars]
    if any(stamps[i]-stamps[i-1]!=timedelta(minutes=1)
           for i in range(1,len(stamps))):
        return None
    info=classify_completed_regime(bars)
    if info is None:
        return None
    if info.median_swing_bps is not None and info.median_swing_bps<=2*spread_bps:
        return "SPREAD_DOMINATED_SWINGS"
    if info.regime=="SIDEVEIS_RYTME_WHIPSAW_KANDIDAT":
        return "OSCILLATING_CHOP"
    if info.regime=="RETNINGSTREND_KANDIDAT":
        return "DIRECTIONAL_TREND"
    return "MIXED_STRUCTURE"


def _at_bars(bars,start,end):
    return [b for b in bars if start<=utc(b.bar_time)<end]


def build_causal_gate_windows(*,bars,points,spread_bps:float,
                              start=None,end=None,lookback=30,horizon=30):
    if lookback!=30 or horizon!=30:
        raise ValueError("V1 fixed completed 30m shape and next 30m PAPER outcome")
    if spread_bps<0:raise ValueError("spread scenario must be nonnegative")
    if not bars or not points:return ()
    ordered=sorted(bars,key=lambda b:utc(b.bar_time))
    paper=sorted(points,key=lambda p:utc(p.at))
    if start is None: start=utc(ordered[0].bar_time)+timedelta(minutes=lookback)
    if end is None:end=min(utc(ordered[-1].bar_time)+timedelta(minutes=1),
                           utc(paper[-1].at))
    start,end=utc(start),utc(end)
    # Canonical 30m decision grid in UTC; label availability is enforced
    # before each constructed window.
    step=timedelta(minutes=30)
    snap=int(start.timestamp())
    first=datetime.fromtimestamp(((snap+1799)//1800)*1800,tz=timezone.utc)
    value_by_time={utc(p.at):float(p.nav_nok) for p in paper}
    samples=[]
    t=first
    while t+step<=end:
        prior=_at_bars(ordered,t-step,t)
        if len(prior)==30:
            prior_regime=classify_completed_regime(prior)
            # First PAPER point strictly at t, second at t+30,
            # from same causal strategy replay (no lookahead in inputs).
            v0=value_by_time.get(t)
            v1=value_by_time.get(t+step)
            if prior_regime and v0 is not None and v1 is not None and v0>0:
                # If gaps occur in future 30m, discard rather than treat
                # the missing time as 0 return.
                following=_at_bars(ordered,t,t+step)
                if len(following)==30 and all(
                    utc(b.bar_time)==t+timedelta(minutes=k)
                    for k,b in enumerate(following)):
                    key=gate_class_for_completed_bars_v1(prior,spread_bps)
                    if key is None:
                        t+=step
                        continue
                    samples.append(GateWindow(
                        t,t+step,key,prior_regime.regime,
                        prior_regime.efficiency_ratio,
                        prior_regime.completed_turns,
                        prior_regime.median_swing_bps,
                        prior_regime.range_bps,float(spread_bps),
                        100*(v1/v0-1),
                    ))
        t+=step
    return tuple(samples)


def evaluate_trade_gate_train_holdout(windows:Sequence[GateWindow],
                                      *,train_share=.7,min_per_class=4,
                                      min_train=14,min_test=5):
    if not .55<=train_share<=.85:
        raise ValueError("invalid train fraction")
    ordered=sorted(windows,key=lambda x:x.decision_at)
    if len(ordered)<min_train+min_test+1:
        return None
    cutoff_index=int(len(ordered)*train_share)
    cutoff=ordered[cutoff_index].decision_at
    # At t, model can know outcome only if its end is STRICTLY before
    # first holdout decision; training rows touching holdout are purged.
    train=tuple(w for w in ordered[:cutoff_index] if w.future_until<cutoff)
    test=tuple(w for w in ordered[cutoff_index:] if w.decision_at>=cutoff)
    if len(train)<min_train or len(test)<min_test:return None
    learned={}
    for category in sorted({x.class_key for x in train}):
        values=[x.future_paper_nav_pct for x in train if x.class_key==category]
        if len(values)>=min_per_class:
            avg=mean(values)
            learned[category]=("TRADE" if avg>0 else "SKIP",len(values),avg)
    if not learned:return None
    adopted=[x for x in test if learned.get(x.class_key,("ABSTAIN",0,0))[0]=="TRADE"]
    skipped=[x for x in test if learned.get(x.class_key,("ABSTAIN",0,0))[0]=="SKIP"]
    unknown=[x for x in test if x.class_key not in learned]
    # "sum_pct" is the sum of non-overlapping interval returns, not
    # compounded account performance. Strongly non-executable proxy.
    return GateEvaluation(
        train_windows=len(train),test_windows=len(test),
        purged_windows=len(ordered[:cutoff_index])-len(train),
        abstained_windows=len(unknown),train_cutoff=cutoff,
        trained_actions=tuple((k,*v) for k,v in sorted(learned.items())),
        holdout_baseline_sum_pct=sum(x.future_paper_nav_pct for x in test),
        holdout_only_allowed_sum_pct=sum(x.future_paper_nav_pct for x in adopted),
        holdout_skipped_positive_sum_pct=sum(max(0,x.future_paper_nav_pct) for x in skipped),
        holdout_skipped_negative_sum_pct=sum(min(0,x.future_paper_nav_pct) for x in skipped),
        holdout_predicted_trade_windows=len(adopted),
        warning=("Not a net backtest of going FLAT: exiting, re-entry, "
                 "funding and changed strategy state absent. Never use as LIVE.")
    )


def replay_trained_gate_holdout_v1(*,bars,costs,strategy_key:str,
                                   timeframe:str,evaluation:GateEvaluation,
                                   baseline=None):
    """Freeze train-only actions, then replay BOTH models on the same bars.

    The policy is entirely inactive before the held-out cutoff, ensuring
    identical initial inventory/NAV. After cutoff a STOP closes on next open
    with normal modeled spread, fees and delayed re-entry. Unknown evidence
    is never interpreted as a positive GO signal.
    """
    from strategy_lab_v2_replay import replay_v3_strategy_v2

    frozen={key:action for key,action,_,_ in evaluation.trained_actions}
    cutoff=utc(evaluation.train_cutoff)

    def paper_gate(closed,visible):
        if closed<cutoff:
            return True
        category=gate_class_for_completed_bars_v1(visible,costs.spread_bps)
        return category is not None and frozen.get(category)=="TRADE"

    original=baseline or replay_v3_strategy_v2(
        strategy_key=strategy_key,bars=bars,costs=costs,timeframe=timeframe)
    gated=replay_v3_strategy_v2(
        strategy_key=strategy_key,bars=bars,costs=costs,timeframe=timeframe,
        paper_gate=paper_gate)
    def at_cutoff(result):
        return next((p for p in result.points if p.at==cutoff),None)
    first_original=at_cutoff(original)
    first_gated=at_cutoff(gated)
    if first_original is None or first_gated is None:
        raise ValueError("complete identical holdout cutoff is required")
    if (abs(first_original.nav_nok-first_gated.nav_nok)>1e-7 or
        abs(first_original.lots-first_gated.lots)>1e-9):
        raise ValueError("PAPER gate changed baseline before holdout")
    if not original.points or not gated.points or first_original.nav_nok<=0:
        raise ValueError("valid positive PAPER NAV required")
    if original.points[-1].at!=gated.points[-1].at:
        raise ValueError("replays must cover identical source intervals")
    pct=lambda result:100*(result.points[-1].nav_nok/first_original.nav_nok-1)
    originals=tuple(e for e in original.events if e.at>=cutoff)
    candidates=tuple(e for e in gated.events if e.at>=cutoff)
    def holdout_drawdown(points):
        peak=first_original.nav_nok
        worst=0.
        for point in points:
            if point.at<cutoff:
                continue
            peak=max(peak,point.nav_nok)
            worst=max(worst,100*(peak-point.nav_nok)/peak)
        return worst
    a,b=pct(original),pct(gated)
    return GateFullReplayComparison(
        cutoff=cutoff,baseline_holdout_pct=a,gated_holdout_pct=b,
        gated_minus_baseline_pct=b-a,
        baseline_orders=len(originals),gated_orders=len(candidates),
        baseline_cost_nok=sum(e.cost_nok for e in originals),
        gated_cost_nok=sum(e.cost_nok for e in candidates),
        baseline_max_drawdown_pct=holdout_drawdown(original.points),
        gated_max_drawdown_pct=holdout_drawdown(gated.points),
        cost_source=costs.source,
        warning=("PAPER next-open fills with scenario spread/fees; not Saxo "
                 "fills or real net account performance. No LIVE promotion."),
    )
