"""Evidence-only calibration/validation. No market access or order execution.

A reconciliation timestamp is not a fill timestamp. Only exact matched
broker final-fill observations are eligible for price/latency calibration.
Validation is frozen before the holdout begins. Unmatched intents count
against coverage; they are not silently removed from the denominator.
"""
from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from statistics import median


def _aware(t):
    if not isinstance(t,datetime) or t.tzinfo is None:
        raise ValueError("timezone-aware evidence required")
    return t


def _quantile(values,p):
    ordered=sorted(values)
    if not ordered:
        return None
    x=(len(ordered)-1)*p
    i=int(x)
    return ordered[i]+(ordered[min(i+1,len(ordered)-1)]-ordered[i])*(x-i)


@dataclass(frozen=True)
class VerifiedFill:
    decision_id: str
    instance_id: str
    instrument_key: str
    side: str
    amount: float
    decided_at: datetime
    filled_at: datetime
    price: float
    bid: float
    ask: float
    quote_received_at: datetime
    price_source: str = "UNVERIFIED"

    def __post_init__(self):
        for t in (self.decided_at,self.filled_at,self.quote_received_at):
            _aware(t)
        if not self.decision_id or not self.instance_id or not self.instrument_key:
            raise ValueError("exact decision and instrument identity required")
        if self.price_source!="SAXO_FINAL_FILL" or self.side not in ("BUY","SELL"):
            raise ValueError("verified FinalFill required")
        if not all(isfinite(x) and x>0 for x in (self.amount,self.price,self.bid,self.ask)) or self.ask<self.bid:
            raise ValueError("invalid verified fill")
        if self.filled_at<self.decided_at or not 0<=(self.filled_at-self.quote_received_at).total_seconds()<=2:
            raise ValueError("missing contemporaneous observable BBO")

    @property
    def latency(self):
        return (self.filled_at-self.decided_at).total_seconds()

    @property
    def signed_slippage(self):
        return self.price-self.ask if self.side=="BUY" else self.bid-self.price


@dataclass(frozen=True)
class Calibration:
    instrument_key: str
    frozen_at: datetime
    sample_count: int
    latency_p50: float
    latency_p95: float
    slippage_p50: float
    slippage_p95: float


def calibrate_fills(observations, *, frozen_at, minimum=30):
    """Empirical distribution; no margin/fee assumptions derived from prices."""
    _aware(frozen_at)
    rows=tuple(observations)
    if len({(r.instance_id,r.decision_id) for r in rows})!=len(rows):
        raise ValueError("duplicate fill evidence")
    if len(rows)<minimum or minimum<1:
        raise ValueError("insufficient calibration fills")
    instruments={r.instrument_key for r in rows}
    if len(instruments)!=1 or any(r.filled_at>=frozen_at for r in rows):
        raise ValueError("mixed instrument or calibration/holdout leakage")
    lat=[r.latency for r in rows]
    slip=[r.signed_slippage for r in rows]
    return Calibration(next(iter(instruments)),frozen_at,len(rows),
                       median(lat),_quantile(lat,.95),median(slip),_quantile(slip,.95))


@dataclass(frozen=True)
class IntentOutcome:
    """One complete observable intent per source/decision id, including vetoes."""
    instance_id: str
    instrument_key: str
    decision_id: str
    decided_at: datetime
    target: float
    inventory_after: float
    outcome: str
    fill_price: float | None = None
    filled_at: datetime | None = None
    side: str | None = None
    amount: float | None = None
    verified: bool = False

    def __post_init__(self):
        _aware(self.decided_at)
        if not all(isfinite(x) for x in (self.target,self.inventory_after)):
            raise ValueError("nonfinite intent")
        if self.filled_at is not None and _aware(self.filled_at)<self.decided_at:
            raise ValueError("fill before intent")
        for x in (self.fill_price,self.amount):
            if x is not None and (not isfinite(x) or x<=0):
                raise ValueError("invalid fill value")


def compare_holdout(calibration, live, sim, *, minimum=100, min_coverage=.95,
                    min_target_agreement=.95, min_inventory_agreement=.95,
                    max_price_mae=2., max_latency_mae=2.):
    """Provisional acceptance contract; no automatic LIVE promotion.

    At least 100 matched independent holdout intents and an explicit
    verified price subset. Unmatched/missing/unknown outcomes fail coverage.
    Tolerances are research defaults, to be frozen before the experiment.
    """
    def keyed(rows):
        result={}
        for r in rows:
            _aware(r.decided_at)
            if r.decided_at<calibration.frozen_at or r.instrument_key!=calibration.instrument_key:
                raise ValueError("not an independent instrument-matched holdout")
            k=(r.instance_id,r.decision_id)
            if k in result:
                raise ValueError("ambiguous duplicate intent")
            result[k]=r
        return result
    a,b=keyed(live),keyed(sim)
    keys=set(a)|set(b)
    paired=set(a)&set(b)
    coverage=len(paired)/len(keys) if keys else 0.
    targets=inventories=outcomes=0
    prices=[]; latencies=[]
    live_fills=0
    for k in keys:
        l=a.get(k); s=b.get(k)
        if l is not None and l.outcome=="FILLED":
            live_fills+=1
        if l is None or s is None:
            continue
        if l.outcome in ("UNKNOWN","UNOBSERVED","PENDING") or s.outcome in ("UNKNOWN","UNOBSERVED","PENDING"):
            continue
        targets+=int(abs(l.target-s.target)<=1e-9)
        inventories+=int(abs(l.inventory_after-s.inventory_after)<=1e-9)
        outcomes+=int(l.outcome==s.outcome)
        if (l.outcome==s.outcome=="FILLED" and l.verified
            and l.side==s.side and l.side in ("BUY","SELL")
            and l.amount is not None and s.amount is not None and abs(l.amount-s.amount)<=1e-9
            and l.fill_price is not None and s.fill_price is not None
            and l.filled_at is not None and s.filled_at is not None):
            prices.append(abs(l.fill_price-s.fill_price))
            latencies.append(abs((l.filled_at-l.decided_at).total_seconds()
                                -(s.filled_at-s.decided_at).total_seconds()))
    n=max(1,len(keys))
    price_mae=sum(prices)/len(prices) if prices else None
    latency_mae=sum(latencies)/len(latencies) if latencies else None
    fill_coverage=len(prices)/live_fills if live_fills else 0.
    passed=(len(paired)>=minimum and coverage>=min_coverage
        and targets/n>=min_target_agreement and inventories/n>=min_inventory_agreement
        and outcomes/n>=min_coverage and len(prices)>=30 and fill_coverage>=min_coverage
        and price_mae is not None and price_mae<=max_price_mae
        and latency_mae is not None and latency_mae<=max_latency_mae)
    return {"passed":passed,"union":len(keys),"paired":len(paired),
            "coverage":coverage,"target_agreement":targets/n,"inventory_agreement":inventories/n,
            "outcome_agreement":outcomes/n,"verified_fill_coverage":fill_coverage,
            "verified_pairs":len(prices),"price_mae_points":price_mae,"latency_mae_s":latency_mae,
            "pnl_validated":False,
            "status":"EXECUTION_CHECK_PASSED" if passed else "INSUFFICIENT_OR_DIVERGENT"}


@dataclass(frozen=True)
class AccountWindow:
    instance_id: str
    start: datetime
    end: datetime
    live_start_nok: float
    live_end_nok: float
    live_external_flows_nok: float
    sim_start_nok: float
    sim_end_nok: float
    sim_external_flows_nok: float
    verified: bool
    includes_all_costs: bool


def validate_account_pnl(execution_report, windows, *, frozen_at,
                         min_windows=10, max_error_pct=.5):
    """Compare net equity changes on disjoint account windows.

    External transfers are removed; fees, financing and open-position marks
    must be included in verified ending equity. No inference from NAV alone.
    Error is percentage points of initial LIVE equity, not relative to profit.
    """
    _aware(frozen_at)
    rows=sorted(windows,key=lambda r:(r.instance_id,r.start))
    errors=[]
    last_end={}
    for r in rows:
        if (not r.instance_id or _aware(r.start)<frozen_at or _aware(r.end)<=r.start
            or r.start<last_end.get(r.instance_id,frozen_at)):
            raise ValueError("overlap or pre-calibration account window")
        last_end[r.instance_id]=r.end
        if not r.verified or not r.includes_all_costs:
            continue
        v=(r.live_start_nok,r.live_end_nok,r.live_external_flows_nok,
           r.sim_start_nok,r.sim_end_nok,r.sim_external_flows_nok)
        if not all(isfinite(x) for x in v) or min(r.live_start_nok,r.sim_start_nok)<=0:
            continue
        if abs(r.live_start_nok-r.sim_start_nok)>0.01:
            continue
        actual=r.live_end_nok-r.live_start_nok-r.live_external_flows_nok
        paper=r.sim_end_nok-r.sim_start_nok-r.sim_external_flows_nok
        errors.append(100*abs(actual-paper)/r.live_start_nok)
    p95=_quantile(errors,.95)
    verified=(len(errors)>=min_windows and len(errors)==len(rows)
              and p95 is not None and p95<=max_error_pct)
    return {**execution_report,"pnl_validated":bool(verified and execution_report.get("passed")),
            "pnl_windows":len(rows),"pnl_verified_windows":len(errors),
            "pnl_error_p95_percentage_points":p95}
