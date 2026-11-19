"""Conservative 1m-close-only PAPER exit counterfactuals for V3 regime trades.

Uses the SAME entry signals and costs as Strategy Lab v2. After a protective
exit, re-entry is forbidden until the unchanged baseline next enters anew.
This is intentionally NOT a full feedback-aware strategy replay or LIVE stop.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta, timezone
from math import isfinite


@dataclass(frozen=True)
class ProtectionTrialV1:
    label: str
    episodes: int
    protective_exits: int
    profit_exits: int
    adverse_exits: int
    baseline_net_nok: float
    scenario_net_nok: float
    difference_nok: float
    improved_episodes: int
    worsened_episodes: int
    complex_episodes_excluded: int
    incomplete_episodes_excluded: int


def _utc(value):
    if value.tzinfo is None:
        raise ValueError('PAPER bars require timezone-aware timestamps')
    return value.astimezone(timezone.utc)


def _completed_episodes(events):
    """Only one immutable tranche per episode: no fictitious weighted fills."""
    completed=[]; open_event=None; complex_count=0; incomplete=0; complex_open=False
    for event in events:
        kind=str(event.kind)
        before,after=float(event.prior_lots),float(event.after_lots)
        if kind=='OPEN' and abs(before)<1e-9 and abs(after)>1e-9:
            if open_event is not None:incomplete+=1
            open_event=event;complex_open=False
        elif open_event is not None and kind in ('ADD','REDUCE'):
            complex_open=True
        elif open_event is not None and kind in ('CLOSE','GAP_FLAT') and abs(after)<1e-9:
            if complex_open:complex_count+=1
            else:completed.append((open_event,event))
            open_event=None;complex_open=False
    if open_event is not None:incomplete+=1
    return tuple(completed),complex_count,incomplete


def _per_side_cost(price,qty,costs):
    return (abs(qty)*price*float(costs.point_value_nok)*
            (float(costs.spread_bps)/20000.+float(costs.variable_fee_bps)/10000.)
            +float(costs.fixed_fee_nok))


def _atr_before_entry(bars,at,lookback=14):
    """ATR may use ONLY 14 complete bars strictly BEFORE the fill time."""
    eligible=[b for b in bars if _utc(b.bar_time)+timedelta(minutes=1)<=at]
    if len(eligible)<lookback+1:return None
    tail=eligible[-(lookback+1):]
    if any(_utc(n.bar_time)-_utc(p.bar_time)!=timedelta(minutes=1)
           for p,n in zip(tail,tail[1:])):
        return None
    true_ranges=[]
    for previous,current in zip(tail,tail[1:]):
        h,l,pc=float(current.high),float(current.low),float(previous.close)
        true_ranges.append(max(h-l,abs(h-pc),abs(l-pc)))
    return sum(true_ranges)/len(true_ranges)


def compare_exit_protection_v1(*,replay,bars,costs,
                               givebacks=(.25,.50,.75),
                               min_peak_cost_multiple=2.,
                               adverse_atr_multiple=1.5,
                               window_start=None,window_end=None):
    """Next 1m OPEN exits, never same-bar/favourable wick fill.

    Only independently completed single-tranche baseline episodes count.
    Baseline next entry is the earliest permitted new entry after early exit.
    An unfinished or size-changing episode is excluded; source gaps are
    handled by the baseline's explicit GAP_FLAT with no fabricated new fill.
    """
    if (not isfinite(float(min_peak_cost_multiple)) or min_peak_cost_multiple<1
        or not isfinite(float(adverse_atr_multiple)) or adverse_atr_multiple<=0):
        raise ValueError('invalid research parameters')
    fractions=tuple(float(x) for x in givebacks)
    if any(not isfinite(x) or x<=0 or x>=1 for x in fractions):
        raise ValueError('giveback must be between zero and one')
    begin=_utc(window_start) if window_start is not None else None
    finish=_utc(window_end) if window_end is not None else None
    if begin is not None and finish is not None and finish<=begin:
        raise ValueError('invalid PAPER observation window')
    ordered=tuple(sorted(bars,key=lambda x:_utc(x.bar_time)))
    if any(_utc(n.bar_time)<=_utc(p.bar_time) for p,n in zip(ordered,ordered[1:])):
        raise ValueError('duplicate or reversed 1m source')
    by_open={_utc(b.bar_time):b for b in ordered}
    completed,complex_count,incomplete=_completed_episodes(replay.events)
    out=[]
    for giveback in (None,'ATR',)+fractions:
        baseline_sum=scenario_sum=0.
        triggers=profit_triggers=adverse_triggers=better=worse=eligible=0
        for opened,closed in completed:
            start,end=_utc(opened.at),_utc(closed.at)
            if (end<=start or (begin is not None and start<begin)
                or (finish is not None and end>finish)):
                continue
            direction=1 if float(opened.after_lots)>0 else -1
            qty=abs(float(opened.after_lots))
            price=float(opened.price)
            baseline=(direction*qty*(float(closed.price)-price)*float(costs.point_value_nok)
                      -float(opened.cost_nok)-float(closed.cost_nok))
            baseline_sum+=baseline
            scenario=baseline
            if giveback is not None:
                atr=_atr_before_entry(ordered,start)
                roundtrip_cost=float(opened.cost_nok)+_per_side_cost(price,qty,costs)
                min_profit=float(min_peak_cost_multiple)*roundtrip_cost
                initial_stop=max(float(adverse_atr_multiple)*atr if atr else float('inf'),
                                 2*price*float(costs.spread_bps)/10000.)
                peak=0.
                at=start+timedelta(minutes=1)
                while at<end:
                    previous=by_open.get(at-timedelta(minutes=1))
                    next_bar=by_open.get(at)
                    if previous is None or next_bar is None:
                        break  # no imaginary jump across a market-data gap
                    if _utc(next_bar.bar_time)-_utc(previous.bar_time)!=timedelta(minutes=1):
                        break
                    mark=float(previous.close)
                    net=(direction*qty*(mark-price)*float(costs.point_value_nok)
                         -float(opened.cost_nok)-_per_side_cost(mark,qty,costs))
                    peak=max(peak,net)
                    profit_hit=(giveback!='ATR' and peak>=min_profit
                                and net<=peak*(1.-giveback))
                    adverse_hit=(isfinite(initial_stop) and
                                 direction*(mark-price)<=-initial_stop)
                    if profit_hit or adverse_hit:
                        exit_price=float(next_bar.open)
                        scenario=(direction*qty*(exit_price-price)*float(costs.point_value_nok)
                                  -float(opened.cost_nok)-_per_side_cost(exit_price,qty,costs))
                        triggers+=1
                        if profit_hit:profit_triggers+=1
                        else:adverse_triggers+=1
                        if scenario>baseline+1e-8:better+=1
                        if scenario<baseline-1e-8:worse+=1
                        break
                    at+=timedelta(minutes=1)
            scenario_sum+=scenario
            eligible+=1
        out.append(ProtectionTrialV1(
            ('Uendret strategi' if giveback is None else
             'Kun ATR-stopp' if giveback=='ATR' else
             f'{giveback:.0%} tilbakegang + ATR-stop'),
            eligible,triggers,profit_triggers,adverse_triggers,
            round(baseline_sum,2),round(scenario_sum,2),
            round(scenario_sum-baseline_sum,2),better,worse,
            complex_count,incomplete))
    return tuple(out)


__all__=['ProtectionTrialV1','compare_exit_protection_v1']
