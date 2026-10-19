"""Saxo official historical performance (account-scoped GET-only, EOD).

Performance v4 (TimeWeighted, Balance, AccumulatedProfitLoss) is an
independent, broker-calculated result source. Do not infer 1m strategy
attribution from EOD account totals. Never replace gaps with zeroes.
"""
from __future__ import annotations

from datetime import date,datetime,timedelta,timezone
from math import isfinite
from typing import Mapping
from database import connect

SOURCE="SAXO_HIST_V4_PERFORMANCE_ACCOUNT_KEY"


def _numeric(value):
    if value is None:
        return None
    if isinstance(value,bool):
        raise ValueError("NON_NUMERIC_PERFORMANCE")
    number=float(value)
    if not isfinite(number):
        raise ValueError("NONFINITE_PERFORMANCE")
    return number


def _dated_series(payload,name,field):
    obj=payload.get(name)
    if obj is None:
        return {}
    if not isinstance(obj,Mapping):
        raise ValueError("PERFORMANCE_SERIES_INVALID")
    raw=obj.get(field)
    if raw is None:
        return {}
    if not isinstance(raw,list):
        raise ValueError("PERFORMANCE_TIME_VALUES_INVALID")
    rows={}
    for x in raw:
        if not isinstance(x,Mapping):
            raise ValueError("PERFORMANCE_TIME_POINT_INVALID")
        when=str(x.get("Date") or "")[:10]
        d=date.fromisoformat(when).isoformat()
        val=_numeric(x.get("Value"))
        if val is None or d in rows:
            raise ValueError("PERFORMANCE_VALUE_MISSING_OR_DUPLICATE")
        rows[d]=val
    return rows


def parse_official_performance_v1(payload:Mapping,*,from_date:date,to_date:date):
    """Return dated values without any interpolation or invented cashflows."""
    if not isinstance(payload,Mapping):
        raise ValueError("SAXO_PERFORMANCE_INVALID")
    paths=[
        ("Balance","AccountValue","account_value"),
        ("Balance","AccountBalance","account_balance"),
        ("Balance","CashTransfer","cash_transfer"),
        ("Balance","SecurityTransfer","security_transfer"),
        ("TimeWeighted","Accumulated","time_weighted_fraction"),
    ]
    parsed=[(col,_dated_series(payload,section,key)) for section,key,col in paths]
    dates=sorted(set().union(*(set(v) for _,v in parsed)))
    results=[]
    for d in dates:
        if not from_date.isoformat()<=d<=to_date.isoformat():
            raise ValueError("PERFORMANCE_DATE_OUTSIDE_REQUEST")
        results.append({"value_date":d,**{column:data.get(d) for column,data in parsed}})
    return tuple(results)


def parse_saxo_profit_summary_v1(payload:Mapping,*,from_date:date,to_date:date):
    """Saxo's own account-wide P/L, not a strategy or intraday estimate."""
    if not isinstance(payload,Mapping):
        raise ValueError("SAXO_PERFORMANCE_SUMMARY_INVALID")
    pnl=_numeric(payload.get("AccumulatedProfitLoss"))
    if pnl is None:
        return {"status":"BROKER_PNL_MISSING","profit":None,"last_trade_day":None}
    last=payload.get("LastTradeDay")
    if last:
        try: last_day=date.fromisoformat(str(last)[:10])
        except ValueError: raise ValueError("BROKER_LAST_TRADE_DATE_INVALID")
        if last_day>to_date:
            raise ValueError("BROKER_LAST_TRADE_DATE_IN_FUTURE")
    else:
        last_day=None
    returned_start=payload.get("From")
    returned_end=payload.get("Thru")
    if returned_start is not None and date.fromisoformat(str(returned_start)[:10])<from_date:
        raise ValueError("BROKER_PERIOD_UNEXPECTED_START")
    if returned_end is not None and date.fromisoformat(str(returned_end)[:10])>to_date:
        raise ValueError("BROKER_PERIOD_UNEXPECTED_END")
    return {"status":"SAXO_REPORTED_ACCOUNT_PNL","profit":pnl,
            "last_trade_day":last_day.isoformat() if last_day else None}


def ensure_official_performance_schema_v1(*,db_path="pricegauger.db"):
    with connect(db_path) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS pg_saxo_account_perf_daily_v1(
          account_id TEXT NOT NULL,currency TEXT NOT NULL,value_date TEXT NOT NULL,
          fetched_at TEXT NOT NULL,source TEXT NOT NULL,
          account_value DOUBLE PRECISION,account_balance DOUBLE PRECISION,
          cash_transfer DOUBLE PRECISION,security_transfer DOUBLE PRECISION,
          time_weighted_fraction DOUBLE PRECISION,
          PRIMARY KEY(account_id,value_date)
        )""")
        db.execute("""CREATE TABLE IF NOT EXISTS pg_saxo_account_perf_summary_v1(
          account_id TEXT NOT NULL,currency TEXT NOT NULL,
          period_from TEXT NOT NULL,period_to TEXT NOT NULL,
          fetched_at TEXT NOT NULL,source TEXT NOT NULL,
          status TEXT NOT NULL,profit DOUBLE PRECISION,
          last_trade_day TEXT,
          PRIMARY KEY(account_id,period_from,period_to)
        )""")


def save_official_performance_v1(*,account_id:str,currency:str,
                                  daily:tuple[dict,...],
                                  summary:dict,from_date:date,to_date:date,
                                  observed_at:datetime,db_path="pricegauger.db"):
    ensure_official_performance_schema_v1(db_path=db_path)
    stamp=observed_at.astimezone(timezone.utc).isoformat()
    with connect(db_path) as db:
        for row in daily:
            db.execute("""INSERT INTO pg_saxo_account_perf_daily_v1(
              account_id,currency,value_date,fetched_at,source,account_value,
              account_balance,cash_transfer,security_transfer,time_weighted_fraction)
              VALUES(?,?,?,?,?,?,?,?,?,?)
              ON CONFLICT(account_id,value_date) DO UPDATE SET
              currency=excluded.currency,fetched_at=excluded.fetched_at,
              account_value=excluded.account_value,account_balance=excluded.account_balance,
              cash_transfer=excluded.cash_transfer,security_transfer=excluded.security_transfer,
              time_weighted_fraction=excluded.time_weighted_fraction""",(
                account_id,currency,row["value_date"],stamp,SOURCE,
                row["account_value"],row["account_balance"],row["cash_transfer"],
                row["security_transfer"],row["time_weighted_fraction"],
            ))
        db.execute("""INSERT INTO pg_saxo_account_perf_summary_v1(
          account_id,currency,period_from,period_to,fetched_at,source,
          status,profit,last_trade_day) VALUES(?,?,?,?,?,?,?,?,?)
          ON CONFLICT(account_id,period_from,period_to) DO UPDATE SET
          fetched_at=excluded.fetched_at,status=excluded.status,
          profit=excluded.profit,last_trade_day=excluded.last_trade_day""",(
            account_id,currency,from_date.isoformat(),to_date.isoformat(),stamp,
            SOURCE,summary["status"],summary["profit"],summary["last_trade_day"],
        ))


def load_official_performance_v1(*,account_id:str,db_path="pricegauger.db",
                                days:int=100):
    ensure_official_performance_schema_v1(db_path=db_path)
    since=(datetime.now(timezone.utc).date()-timedelta(days=max(1,min(days,365)))).isoformat()
    with connect(db_path) as db:
        rows=db.execute("""SELECT value_date,account_value,account_balance,
          cash_transfer,security_transfer,time_weighted_fraction,currency,fetched_at
          FROM pg_saxo_account_perf_daily_v1 WHERE account_id=? AND value_date>=?
          ORDER BY value_date""",(account_id,since)).fetchall()
        summary=db.execute("""SELECT period_from,period_to,status,profit,
          currency,last_trade_day,fetched_at
          FROM pg_saxo_account_perf_summary_v1 WHERE account_id=?
          ORDER BY fetched_at DESC LIMIT 1""",(account_id,)).fetchone()
    return tuple(dict(x) for x in rows),dict(summary) if summary is not None else None


def collect_official_performance_once_v1(*,broker=None,days:int=90,
                                         db_path="pricegauger.db",
                                         now:datetime|None=None):
    """Fetch each account's *Saxo* historical P/L and TWR, no execution."""
    if broker is None:
        from autotrader_v3_live_saxo_v1 import configured_live_pilot_client_v3
        broker=configured_live_pilot_client_v3()
    if broker is None:
        return {"status":"SAXO_UNAVAILABLE","seen":0,"saved":0,"failed":0}
    if hasattr(broker,"client") and hasattr(broker.client,"timeout"):
        broker.client.timeout=min(float(broker.client.timeout),5.)
    clock=now or datetime.now(timezone.utc)
    if clock.tzinfo is None:
        raise ValueError("UTC_TIMESTAMP_REQUIRED")
    end=clock.astimezone(timezone.utc).date()
    start=end-timedelta(days=min(365,max(2,int(days))))
    try:
        accounts=tuple(broker.accounts())
    except Exception:
        return {"status":"SAXO_ACCOUNTS_FAILED","seen":0,"saved":0,"failed":1}
    seen=saved=failed=0
    errors:dict[str,int]={}
    for a in accounts:
        seen+=1
        phase="ACCOUNT_IDENTITY"
        try:
            if not isinstance(a,Mapping): raise ValueError("INVALID_ACCOUNT")
            aid=str(a["AccountId"]).strip()
            key=str(a["AccountKey"]).strip()
            clientkey=str(a["ClientKey"]).strip()
            curr=str(a["Currency"]).strip().upper()
            if not all((aid,key,clientkey,curr)): raise ValueError("UNVERIFIED_ACCOUNT")
            params={"AccountKey":key,"ClientKey":clientkey,
                    "FromDate":start.isoformat(),"ToDate":end.isoformat()}
            phase="TIMESERIES_GET"
            times=broker.client._get("hist/v4/performance/timeseries",params={
                **params,"FieldGroups":"Balance_AccountValue,Balance_AccountBalance,"
                "Balance_CashTransfer,Balance_SecurityTransfer,TimeWeighted_Accumulated"
            })
            phase="SUMMARY_GET"
            summary=broker.client._get("hist/v4/performance/summary",params=params)
            phase="TIMESERIES_PARSE"
            daily=parse_official_performance_v1(times,from_date=start,to_date=end)
            phase="SUMMARY_PARSE"
            pnl=parse_saxo_profit_summary_v1(summary,from_date=start,to_date=end)
            phase="BROKER_HISTORY_EMPTY"
            if not daily and pnl["profit"] is None:
                raise ValueError("NO_HISTORICAL_BROKER_DATA")
            phase="PERSIST"
            save_official_performance_v1(
                account_id=aid,currency=curr,daily=daily,summary=pnl,
                from_date=start,to_date=end,observed_at=clock,db_path=db_path)
            saved+=1
        except Exception as exc:
            failed+=1
            # Only report bounded phase and HTTP class. Never log Saxo
            # payloads, account identifiers, token, amounts or exception text.
            status=getattr(exc,"status_code",None)
            suffix=f"_HTTP_{status}" if isinstance(status,int) and 400<=status<=599 else ""
            code=phase+suffix
            errors[code]=errors.get(code,0)+1
    result={"status":"OK" if not failed else "PARTIAL",
            "seen":seen,"saved":saved,"failed":failed}
    if failed:
        result["errors"]=dict(sorted(errors.items()))
    return result


__all__=["parse_official_performance_v1","parse_saxo_profit_summary_v1",
         "collect_official_performance_once_v1","load_official_performance_v1"]
