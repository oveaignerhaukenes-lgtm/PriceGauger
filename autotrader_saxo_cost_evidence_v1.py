"""Saxo USNAS100.I cost evidence, read-only GET and archived BBO.

Do not conflate Trade.TotalCost / account currency / trade costs /
spread proxy / financing / FX. Booked historical cost is factual only
when an exact account, product, date and non-null Saxo currency are known.
Info-price cost illustration is indicative at CURRENT price/size, never
a historical transaction. Bid/ask spread is from stored genuine quote
snapshots and can vary sharply around FOMC.

Never places, changes, previews or prechecks an actual order.
"""
from __future__ import annotations

from dataclasses import asdict,dataclass
from datetime import datetime,timedelta,timezone
from math import isfinite
from statistics import mean,median
from typing import Any,Mapping,Sequence
from urllib.parse import quote

from database import connect


@dataclass(frozen=True)
class ArchivedSpreadEvidence:
    uic:int
    requested_hours:int
    observations:int
    first_at:str|None
    last_at:str|None
    data_density_fraction:float
    complete_request:bool
    average_points:float|None
    median_points:float|None
    p90_points:float|None
    mean_bps:float|None
    p90_bps:float|None
    max_bps:float|None
    source:str="LSIM_HYPER_QUOTES_1S_ARCHIVED_BBO"


@dataclass(frozen=True)
class SettledCostEvidence:
    account_id:str
    uic:int
    currency:str|None
    rows:int
    booked_cost_rows:int
    cost_unknown_rows:int
    signed_saxo_total_cost:float|None
    total_debits_abs:float|None
    total_credits:float|None
    realized_pnl_sum:float|None
    pnl_rows:int
    trading_days:tuple[str,...]
    incomplete_intraday_rows:int
    source:str="SAXO_HIST_TRANSACTIONS_GET"


@dataclass(frozen=True)
class IndicativeCostEvidence:
    account_id:str
    uic:int
    asset_type:str
    quantity:float
    price:float
    long_commission:float|None
    short_commission:float|None
    fee_currency:str|None
    long_total_pct:float|None
    short_total_pct:float|None
    verification:str


def _utc(raw):
    t=raw if isinstance(raw,datetime) else datetime.fromisoformat(
        str(raw).replace("Z","+00:00"))
    if t.tzinfo is None:raise ValueError("ambiguous timestamp, UTC required")
    return t.astimezone(timezone.utc)


def archived_bbo_spread(*,uic:int,hours:int=24,limit:int=60000,
                        now:datetime|None=None,db_path="pricegauger.db"):
    """Most recent up-to-limit quote rows, no invented market-open coverage.

    Real spread at each quote = ask-bid.  One full spread is a
    *rough roundtrip* friction estimate for executing buy ask and sell bid
    at one stable midpoint, not an extra charge added atop actual fills.
    """
    if hours not in (1,3,6,12,24,72):
        raise ValueError("unsupported quote window")
    if not 1000<=limit<=100000:
        raise ValueError("bounded BBO query required")
    clock=_utc(now or datetime.now(timezone.utc))
    start=clock-timedelta(hours=hours)
    with connect(db_path) as db:
        rows=db.execute("""SELECT quote_at,bid,ask FROM lsim_hyper_quotes_1s
            WHERE provider_uic=? AND quote_at>=? AND quote_at<=?
            ORDER BY quote_at DESC LIMIT ?""",(
            int(uic),start.isoformat(),clock.isoformat(),limit+1)).fetchall()
    truncated=len(rows)>limit
    if truncated:rows=rows[:limit]
    accepted=[]
    for row in reversed(rows):
        try:
            at=_utc(row["quote_at"])
            bid=float(row["bid"]);ask=float(row["ask"])
        except (ValueError,TypeError,OverflowError,KeyError):
            continue
        if not all(isfinite(x) for x in (bid,ask)) or bid<=0 or ask<bid:continue
        midpoint=(bid+ask)/2
        spread=ask-bid
        accepted.append((at,spread,10000*spread/midpoint))
    n=len(accepted)
    if not n:
        return ArchivedSpreadEvidence(int(uic),hours,0,None,None,0.,False,
                                      None,None,None,None,None,None)
    points=sorted(x[1] for x in accepted)
    bps=sorted(x[2] for x in accepted)
    # Observed fraction assumes at most one quote per second. It is a
    # density proxy, NOT a proven proportion of continuous trading hours.
    unique_seconds=len({int(x[0].timestamp()) for x in accepted})
    density=min(1.,unique_seconds/(hours*3600.))
    percentile=lambda v,p:v[min(len(v)-1,max(0,int((len(v)-1)*p)))]
    return ArchivedSpreadEvidence(
        int(uic),hours,n,accepted[0][0].isoformat(),
        accepted[-1][0].isoformat(),density,not truncated,
        mean(points),median(points),percentile(points,.9),
        mean(bps),percentile(bps,.9),max(bps),
    )


def parse_saxo_transactions_costs(*,transactions:Sequence[Mapping],
                                  account_id:str,uic:int):
    """Do not dedupe/aggregate across account ID, UIC or currencies.

    Transaction.TotalCost is Saxo's reported cost; no adding Bookings or
    Trades[].SpreadCost, which might already be included in TotalCost.
    A missing cost field is never silently treated as zero. Intraday
    transactions may be provisional and incomplete.
    """
    costs=[];pnl=[];currencies=set();days=set()
    selected=[]
    incomplete=0
    for row in transactions:
        if str(row.get("AccountId") or "")!=str(account_id):
            continue
        instrument=row.get("Instrument") or {}
        if not isinstance(instrument,Mapping):
            continue
        if str(instrument.get("Uic") or "")!=str(int(uic)):
            continue
        selected.append(row)
        cur=str(row.get("Currency") or "").strip().upper()
        if cur:
            currencies.add(cur)
        day=str(row.get("Date") or "")[:10]
        if day:days.add(day)
        if row.get("IsIntradayData") is True or row.get("IsIntraDay") is True:
            incomplete+=1
        try:
            val=float(row["TotalCost"])
            if isfinite(val):costs.append(val)
        except (KeyError,ValueError,TypeError):
            pass
        try:
            val=float(row["RealizedPnL"])
            if isfinite(val):pnl.append(val)
        except (KeyError,ValueError,TypeError):
            pass
    verified_ccy=next(iter(currencies)) if len(currencies)==1 else None
    # Mixed/unknown cost currencies must not be combined.
    valid=verified_ccy is not None
    signed=sum(costs) if valid and costs else None
    return SettledCostEvidence(
        account_id=str(account_id),uic=int(uic),
        currency=verified_ccy,rows=len(selected),
        booked_cost_rows=len(costs),cost_unknown_rows=len(selected)-len(costs),
        signed_saxo_total_cost=signed,
        total_debits_abs=sum(-x for x in costs if x<0) if valid and costs else None,
        total_credits=sum(x for x in costs if x>0) if valid and costs else None,
        realized_pnl_sum=sum(pnl) if valid and pnl else None,
        pnl_rows=len(pnl),trading_days=tuple(sorted(days)),
        incomplete_intraday_rows=incomplete,
    )


def fetch_saxo_historical_costs(*,client,account_key:str,account_id:str,
                                uic:int,asset_type:str,
                                start:datetime,end:datetime,max_pages=6):
    """Historical Transactions: account-scoped Saxo GET only, bounded pages.

    FromDate/ToDate are *dates*, not Oslo 03:00 instants. Show results as
    calendar-day booked costs, not falsely as exact intraday session fees.
    """
    begin,finish=_utc(start),_utc(end)
    if begin>=finish or finish-begin>timedelta(days=15):
        raise ValueError("bounded historical cost lookback is 15 days")
    if max_pages<1 or max_pages>12:raise ValueError("page limit invalid")
    if not account_key or not account_id or int(uic)<=0:
        raise ValueError("account key/account ID/exact Saxo UIC required")
    events=[]
    page=0
    while page<max_pages:
        params={
            "AccountKeys":account_key,"Uics":str(int(uic)),
            "AssetTypes":str(asset_type),
            "FromDate":begin.date().isoformat(),
            "ToDate":finish.date().isoformat(),
            "$skip":page*200,"$top":200,
        }
        response=client._get("hist/v1/transactions",params=params)
        data=response.get("Data")
        if not isinstance(data,list):
            raise ValueError("Saxo transaction response missing Data; no fallback zero")
        events.extend(x for x in data if isinstance(x,Mapping))
        page+=1
        if len(data)<200 and not response.get("__next"):break
        if page>=max_pages and response.get("__next"):
            raise ValueError("Saxo transaction pagination truncated; refusing partial total")
    return parse_saxo_transactions_costs(
        transactions=events,account_id=account_id,uic=uic,
    )


def get_saxo_indicative_costs(*,client,account_key:str,account_id:str,
                             uic:int,asset_type:str,amount:float):
    """Uses existing client info quote and Saxo GET tradingconditions/cost.

    Probe is a server-side illustration. Does NOT call POST/precheck or orders.
    """
    from saxo_provider import SaxoInstrument
    from saxo_low_friction_candidates_v2 import _quote_fields
    from product_browser_keyword_cost_v1 import _verified_cost_probe
    if not account_key or not account_id or amount<=0 or int(uic)<=0:
        raise ValueError("exact account/product/positive legal size required")
    ins=SaxoInstrument(asset="Cfd",uic=int(uic),asset_type=str(asset_type),symbol="")
    raw=client.info_price(ins)
    bid,ask,_=_quote_fields(raw)
    if bid is None or ask is None or not 0<bid<=ask:
        raise ValueError("Saxo quote is unavailable; cannot model trading costs")
    price=(bid+ask)/2
    account=type("SelectedAccount",(),{"account_key":str(account_key)})()
    buy,sell,currency,long_pct,short_pct,err=_verified_cost_probe(
        client,account=account,instrument=ins,amount=float(amount),price=price)
    return IndicativeCostEvidence(
        account_id=str(account_id),uic=int(uic),asset_type=str(asset_type),
        quantity=float(amount),price=price,
        long_commission=buy,short_commission=sell,
        fee_currency=currency,long_total_pct=long_pct,
        short_total_pct=short_pct,
        verification=("SAXO_GET_COST_ILLUSTRATION" if err is None
                      else "UNAVAILABLE_"+str(err)),
    )


def simple_roundtrip_quote_friction(*,spread_points:float,
                                    point_value_nok_per_lot:float,
                                    lots:float):
    """Idealized crossing cost, not charge on top of a fill-aware replay."""
    if min(spread_points,point_value_nok_per_lot,lots)<0:
        raise ValueError("negative inputs")
    return spread_points*point_value_nok_per_lot*lots
