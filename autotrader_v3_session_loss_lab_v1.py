"""Read-only 03:00 Oslo Saxo account forensics and historical replay comparison.

Three evidence classes are deliberately separate:
 - Saxo TotalValue samples: exact account NAV change, NOT trading profit.
 - Reconciled V3 execution ledger: exact account actions, no invented fill price.
 - PAPER replay on canonical 1m Saxo instrument bars: scenario only.

This module never changes V3 configuration/arming, positions or broker orders.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date,datetime,time,timedelta,timezone
from math import isfinite
from statistics import median
from typing import Mapping,Sequence
from zoneinfo import ZoneInfo

OSLO=ZoneInfo("Europe/Oslo")
MAX_BASELINE_DELAY=timedelta(minutes=12)
MAX_END_AGE=timedelta(minutes=15)
MAX_BAR_GAP=timedelta(minutes=1)


def utc(value):
    t=value if isinstance(value,datetime) else datetime.fromisoformat(str(value).replace("Z","+00:00"))
    if t.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return t.astimezone(timezone.utc)


def oslo_session_start(day:date):
    """Saxo daily reset is a user-provided 03:00 Oslo wall-clock boundary."""
    return datetime.combine(day,time(3,0),tzinfo=OSLO).astimezone(timezone.utc)


def current_oslo_session(*,now=None):
    at=utc(now or datetime.now(timezone.utc)).astimezone(OSLO)
    day=at.date() if at.time()>=time(3) else at.date()-timedelta(days=1)
    return oslo_session_start(day)


@dataclass(frozen=True)
class AccountSessionResult:
    account_id:str
    account_name:str
    currency:str
    start_observed_at:datetime|None
    end_observed_at:datetime|None
    baseline_delay_minutes:float|None
    latest_age_minutes:float|None
    samples:int
    baseline_value:float|None
    latest_value:float|None
    nav_change:float|None
    nav_change_pct:float|None
    worst_observed_drawdown_pct:float|None
    status:str


def account_session_result(*,account_id:str,samples:Sequence[Mapping],
                           start:datetime,end:datetime)->AccountSessionResult:
    """No interpolation to 03:00, no cross-account/currency mixing."""
    begin,stop=utc(start),utc(end)
    if stop<=begin:raise ValueError("invalid window")
    if any(str(s.get("account_id"))!=str(account_id) for s in samples):
        raise ValueError("cross-account NAV source rejected")
    ordered=sorted(samples,key=lambda s:utc(s["observed_at"]))
    name=str(ordered[-1].get("account_name") or account_id) if ordered else str(account_id)
    currencies={str(s.get("currency") or "").upper() for s in ordered}
    if len(currencies)>1:
        raise ValueError("mixed account currencies")
    currency=next(iter(currencies),"")
    good=[]
    for sample in ordered:
        when=utc(sample["observed_at"])
        if not begin<=when<=stop:continue
        if str(sample.get("calculation_reliability") or "").lower()!="ok":
            continue
        try:
            val=float(sample["total_value"])
        except (KeyError,ValueError,TypeError):
            continue
        if isfinite(val) and val>0:
            good.append((when,val))
    if not good:
        return AccountSessionResult(account_id,name,currency,None,None,None,None,
                                    0,None,None,None,None,None,"NO_VERIFIED_NAV")
    # All 03:00 baselines are first verified observations AT/AFTER reset.
    # An observation just BEFORE reset is a previous-day NAV value.
    first,val0=good[0]
    last,val1=good[-1]
    delay=(first-begin).total_seconds()/60.
    age=(stop-last).total_seconds()/60.
    status=("BASELINE_TOO_LATE" if first-begin>MAX_BASELINE_DELAY else
            "LATEST_TOO_OLD" if stop-last>MAX_END_AGE else
            "INSUFFICIENT_SAMPLES" if len(good)<2 else "OBSERVED_NAV_UNADJUSTED")
    if status=="BASELINE_TOO_LATE":
        return AccountSessionResult(account_id,name,currency,first,last,delay,age,
                                    len(good),val0,val1,None,None,None,status)
    peak=val0
    dd=0.
    for _,amount in good:
        peak=max(peak,amount)
        dd=max(dd,100.*(peak-amount)/peak)
    change=val1-val0 if len(good)>1 else None
    pct=100.*change/val0 if change is not None else None
    return AccountSessionResult(
        account_id,name,currency,first,last,delay,age,len(good),
        val0,val1,change,pct,dd if len(good)>1 else None,status,
    )


def summarize_fleet_sessions(results:Sequence[AccountSessionResult]):
    """Sums only within verified identical currency and aligned baseline."""
    grouped={}
    for x in results:
        if x.nav_change is None or x.status!="OBSERVED_NAV_UNADJUSTED":
            continue
        grouped.setdefault(x.currency,[]).append(x)
    return tuple({
        "currency":ccy,"accounts":len(sub),
        "start_total":sum(x.baseline_value for x in sub),
        "end_total":sum(x.latest_value for x in sub),
        "unadjusted_nav_delta":sum(x.nav_change for x in sub),
        "unadjusted_nav_pct":100.*sum(x.nav_change for x in sub)/
                             sum(x.baseline_value for x in sub),
        "warning":"NOT cash-flow-adjusted Saxo daily trading return",
    } for ccy,sub in sorted(grouped.items()))


def filter_reconciled_account_fills(*,executions,account_id,start,end):
    if executions is None:
        return None
    begin,stop=utc(start),utc(end)
    out=[]
    for event in executions:
        if str(event.get("account_id"))!=str(account_id):
            raise ValueError("cross-account reconciled executions")
        at=utc(event["executed_at"])
        if begin<=at<=stop:
            out.append(dict(event))
    return tuple(sorted(out,key=lambda x:utc(x["executed_at"])))


@dataclass(frozen=True)
class CompletedRegime:
    from_at:datetime
    to_at:datetime
    candles:int
    direction_pct:float
    path_bps:float
    range_bps:float
    efficiency_ratio:float
    completed_turns:int
    median_swing_bps:float|None
    regime:str
    note:str


def classify_completed_regime(bars:Sequence,*,min_bars=12)->CompletedRegime|None:
    """Retrospective label only: never use pivot evidence for LIVE signals."""
    ordered=sorted(bars,key=lambda x:utc(x.bar_time))
    if len(ordered)<min_bars:
        return None
    series=[]
    previous=None
    for item in ordered:
        at=utc(item.bar_time)
        op,hi,lo,cl=(float(item.open),float(item.high),
                     float(item.low),float(item.close))
        if (not all(isfinite(y) and y>0 for y in (op,hi,lo,cl))
                or hi<max(op,cl) or lo>min(op,cl)):
            return None
        if previous is not None and at-previous!=MAX_BAR_GAP:
            return None
        series.append((at,op,hi,lo,cl))
        previous=at
    prices=[x[4] for x in series]
    start=prices[0];last=prices[-1]
    path=sum(abs(b-a) for a,b in zip(prices,prices[1:]))
    efficiency=abs(last-start)/path if path>0 else 0.
    scale=median(prices)
    highs=max(x[2] for x in series);lows=min(x[3] for x in series)
    moves=[]
    for i in range(1,len(prices)-1):
        before,mid,after=prices[i-1:i+2]
        if (mid>before and mid>after) or (mid<before and mid<after):
            moves.append(mid)
    swings=[abs(b-a)/scale*10000 for a,b in zip(moves,moves[1:])]
    turns=len(moves)
    drift_bps=10000*(last/start-1)
    range_bps=10000*(highs-lows)/scale
    if efficiency<.24 and turns>=4:
        regime="SIDEVEIS_RYTME_WHIPSAW_KANDIDAT"
        note="Retrospektivt mange svingpunkter mot liten netto fremdrift; test fyllpriser og kostnader."
    elif efficiency>=.56 and abs(drift_bps)>=12:
        regime="RETNINGSTREND_KANDIDAT"
        note="Retrospektivt relativt ensrettet bevegelse; test om lang hold slo flips."
    elif turns>=4:
        regime="BLANDET_CHOP_KANDIDAT"
        note="Retrospektive prisreverseringer; test moderat tregere signaler/flat-filter."
    else:
        regime="UKLART_REGIME"
        note="Ikke nok prisstruktur for en robust klassifikasjon."
    return CompletedRegime(
        series[0][0],series[-1][0]+timedelta(minutes=1),
        len(series),100*(last/start-1),10000*path/scale,
        range_bps,efficiency,turns,median(swings) if swings else None,
        regime,note,
    )


def split_completed_regimes(bars:Sequence,*,minutes=30,
                            start:datetime,end:datetime):
    """Window-by-window, no bridging missing candles or pretending gaps are flat."""
    if minutes not in (15,30,60):
        raise ValueError("unsupported regime window")
    start,end=utc(start),utc(end)
    results=[]
    at=start
    while at+timedelta(minutes=minutes)<=end:
        finish=at+timedelta(minutes=minutes)
        sub=[b for b in bars if at<=utc(b.bar_time)<finish]
        if len(sub)==minutes:
            label=classify_completed_regime(sub)
            if label:results.append(label)
        at=finish
    return tuple(results)


def replay_session_delta(result,*,start:datetime,end:datetime):
    """Compare PAPER NAV against its actual first observed point at/after 03.

    Initial replay starts BEFORE session to warm indicators; it may already
    hold a PAPER position at 03. No synthetic reset/instant close or
    hypothetical Saxo cashflow is inserted.
    """
    begin,stop=utc(start),utc(end)
    points=[p for p in result.points if begin<=utc(p.at)<=stop]
    if len(points)<2:return None
    first,last=points[0],points[-1]
    if utc(first.at)-begin>timedelta(minutes=3):
        return None
    first_nav=float(first.nav_nok);last_nav=float(last.nav_nok)
    if first_nav<=0:return None
    return {
        "strategy":result.strategy,
        "first_at":utc(first.at),
        "last_at":utc(last.at),
        "paper_change_pct":100*(last_nav/first_nav-1),
        "paper_change_scenario_units":last_nav-first_nav,
        "start_position_lots":float(first.lots),
        "end_position_lots":float(last.lots),
        "session_decision_events":sum(begin<=utc(e.at)<=stop for e in result.events),
        "scenario_cost_source":result.cost_source,
        "warning":"PAPER scenario, same-day selection is in-sample, not LIVE proof",
    }


def proposal_from_evidence(*,regimes,account_results,executions_available):
    """Falsifiable A/B experiments, never automated strategy recommendations."""
    loss=sum(x.nav_change_pct is not None and x.nav_change_pct<0 for x in account_results)
    labels=[x.regime for x in regimes]
    proposals=[]
    if labels.count("SIDEVEIS_RYTME_WHIPSAW_KANDIDAT")>=1:
        proposals.append((
            "Retningsfilter + anti-churn",
            "PAPER: V2.1 1m versus V2.1 med bekreftede prisvendinger, "
            "15s inngang og maksimalt ett signal per 15s; mål spread, fills og drawdown."))
    if labels.count("RETNINGSTREND_KANDIDAT")>=1:
        proposals.append((
            "Strukturstyrt hold",
            "PAPER: hold posisjon gjennom to HH/HL eller LL/LH, "
            "skaler ned ved brudd og sammenlign med MACD-flips."))
    if loss>=2:
        proposals.append((
            "Korrelert kontorisiko",
            "Flere samtidige NAV-fall. Mål faktisk samtidighet, "
            "felles strategi-eksponering og regimelag før mekanisk kapitalallokering."))
    if executions_available and loss:
        proposals.append((
            "Ordre-/fyll-latens",
            "Sammenlign mål/ordre/faktisk Saxo-avstemming med siste "
            "kjente pris og regimedata for å skille late exits fra dårlig strategi."))
    if not proposals:
        proposals.append((
            "Datadekning / årsaksavklaring",
            "Hent flere verifiserte Saxo-kontomålinger, avstem innskudd/uttak "
            "og sikre sammenhengende prisbarer før rangering."))
    return tuple(proposals)
