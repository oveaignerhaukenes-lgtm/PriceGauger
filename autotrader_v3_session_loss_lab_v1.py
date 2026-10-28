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
    """Only a complete, synchronized funded-account cohort gets a total.

    No missing account is silently excluded from a reported 'all accounts'
    return. Even an eligible snapshot total is *not* Saxo official daily P/L.
    """
    grouped={}
    for item in results:
        if item.currency:
            grouped.setdefault(item.currency,[]).append(item)
    summaries=[]
    for currency,all_accounts in sorted(grouped.items()):
        valid=[x for x in all_accounts if
               x.status=="OBSERVED_NAV_UNADJUSTED"
               and x.nav_change is not None]
        omitted=[x for x in all_accounts if x not in valid]
        first_times=[x.start_observed_at for x in valid]
        last_times=[x.end_observed_at for x in valid]
        baseline_skew=(max(first_times)-min(first_times)).total_seconds()/60 if first_times else None
        end_skew=(max(last_times)-min(last_times)).total_seconds()/60 if last_times else None
        # Strict 5-minute clock alignment avoids adding a 09:30 account
        # snapshot to another account's 11:55 end-of-day figure.
        aligned=bool(valid and
                     baseline_skew is not None and baseline_skew<=5
                     and end_skew is not None and end_skew<=5)
        complete=bool(aligned and len(valid)==len(all_accounts))
        subtotal_start=sum(x.baseline_value for x in valid)
        subtotal_end=sum(x.latest_value for x in valid)
        subtotal_delta=sum(x.nav_change for x in valid)
        status=("OBSERVED_COHORT_APPROX" if complete else
                "MISSING_ACCOUNT_BASELINE_OR_END" if omitted else
                "ACCOUNT_TIMES_NOT_ALIGNED")
        summaries.append({
            "currency":currency,
            "accounts":len(valid),
            "expected_funded_accounts":len(all_accounts),
            "excluded_accounts":len(omitted),
            "excluded_names":tuple(x.account_name for x in omitted),
            "status":status,
            "baseline_spread_minutes":baseline_skew,
            "last_spread_minutes":end_skew,
            "subtotal_start_only":subtotal_start if valid else None,
            "subtotal_end_only":subtotal_end if valid else None,
            "subtotal_change_only":subtotal_delta if valid else None,
            # Only complete + synchronized data may appear as a total.
            "start_total":subtotal_start if complete else None,
            "end_total":subtotal_end if complete else None,
            "unadjusted_nav_delta":subtotal_delta if complete else None,
            "unadjusted_nav_pct":(
                100.*subtotal_delta/subtotal_start if complete and subtotal_start>0
                else None),
            "warning":"Approximate as-observed NAV only; not Saxo daily performance, not cashflow-adjusted",
        })
    return tuple(summaries)


def funded_account_cohort_v1(*,samples:Sequence[Mapping],end:datetime,
                              lookback_hours:int=24):
    """Select positive-valued observed Saxo accounts; omit known zero balances.

    Avoid treating empty silver accounts as missing funded accounts, while
    retaining the named funded accounts even if the 03:00 slice is absent.
    """
    end_at=utc(end)
    low=end_at-timedelta(hours=lookback_hours)
    latest={}
    for row in samples:
        at=utc(row["observed_at"])
        if not low<=at<=end_at:
            continue
        if str(row.get("calculation_reliability") or "").lower()!="ok":
            continue
        try:
            value=float(row["total_value"])
        except (KeyError,TypeError,ValueError):
            continue
        if not isfinite(value) or value<0:
            continue
        aid=str(row["account_id"])
        previous=latest.get(aid)
        if previous is None or at>previous[0]:
            latest[aid]=(at,value,str(row.get("account_name") or aid))
    funded={aid:record[2] for aid,record in latest.items() if record[1]>0}
    zeroed=tuple(sorted(record[2] for record in latest.values() if record[1]==0))
    return funded,zeroed


def load_exact_product_executions(*,account_id:str,uic:int,asset_type:str,
                                  start:datetime,end:datetime,
                                  db_path="pricegauger.db",limit=1500):
    """Verified RECONCILED execution ledger for ONE account/UIC/asset type.

    Return None when unavailable. We never equate missing telemetry with
    no trading, and never load client-wide positions for account attribution.
    """
    from database import connect
    try:
        with connect(db_path) as db:
            rows=db.execute("""SELECT account_id,instance_id,uic,asset_type,
                   market_name,action,side,direction,amount,
                   inventory_before,inventory_after,executed_at
                   FROM autotrader_v3_execution_events
                   WHERE account_id=? AND uic=? AND asset_type=?
                     AND executed_at>=? AND executed_at<=?
                   ORDER BY executed_at ASC LIMIT ?""",(
                   str(account_id),int(uic),str(asset_type),utc(start).isoformat(),
                   utc(end).isoformat(),max(1,min(5000,int(limit))))
            ).fetchall()
        return tuple(dict(r) for r in rows)
    except Exception:
        return None


def fill_price_followthrough(*,fills,bars,account_id:str,
                             horizons=(1,3,5)):
    """Future market *direction* relative to reconciled position, never P/L.

    Reference is NEXT OBSERVED 1m OPEN after broker confirmation (rather
    than an invented Saxo fill price). No gap interpolation and no use
    of this future evidence in original strategy decisions.
    """
    from bisect import bisect_left
    if fills is None:return None
    ordered=sorted(bars,key=lambda b:utc(b.bar_time))
    times=[utc(b.bar_time) for b in ordered]
    results=[]
    for event in fills:
        if str(event.get("account_id"))!=str(account_id):
            raise ValueError("cross-account fill evidence")
        when=utc(event["executed_at"])
        side=float(event.get("inventory_after") or 0.)
        if abs(side)<1e-12:continue
        # Never anchor to an open recorded before the broker confirmed fill.
        idx=bisect_left(times,when)
        if idx>=len(ordered) or times[idx]-when>timedelta(minutes=2):
            continue
        base=float(ordered[idx].open)
        if base<=0 or not isfinite(base):continue
        outcome={"account_id":str(account_id),
                 "instance_id":str(event.get("instance_id") or ""),
                 "executed_at":when,
                 "action":str(event.get("action") or ""),
                 "signed_lots_after":side,
                 "first_post_confirmation_price_at":times[idx]}
        for mins in horizons:
            value=None
            j=idx+int(mins)
            if j<len(ordered) and times[j]-times[idx]==timedelta(minutes=mins):
                # Must validate *every* intermediate canonical minute;
                # endpoint alignment alone could mask gaps and stale data.
                if all(times[k]-times[k-1]==timedelta(minutes=1)
                       for k in range(idx+1,j+1)):
                    point=float(ordered[j].open)
                    if isfinite(point) and point>0:
                        value=(1 if side>0 else -1)*10000*(point/base-1)
            outcome[f"signed_future_{mins}m_bps"]=value
        results.append(outcome)
    return tuple(results)


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


def market_session_coverage(*,bars,start:datetime,end:datetime):
    """Actual timestamp coverage, no OHLC approximation for missing minutes."""
    first,last=utc(start),utc(end)
    expected=max(0,int((last-first).total_seconds()//60))
    clocks=[utc(b.bar_time) for b in bars if first<=utc(b.bar_time)<last]
    actual=len(set(clocks))
    ratio=actual/expected if expected else 0.
    at_min=min(clocks) if clocks else None
    at_max=max(clocks) if clocks else None
    starts=bool(at_min and (at_min-first)<=timedelta(minutes=3))
    ends=bool(at_max and last-at_max<=timedelta(minutes=4))
    return {
        "expected_1m":expected,"observed_1m":actual,
        "coverage_pct":100*ratio,
        "has_session_start":starts,"has_session_end":ends,
        "comparable":bool(expected>=45 and ratio>=0.80 and starts and ends),
    }


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
    loss=sum(x.status=="OBSERVED_NAV_UNADJUSTED" and x.nav_change_pct is not None
             and x.nav_change_pct<0 for x in account_results)
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
