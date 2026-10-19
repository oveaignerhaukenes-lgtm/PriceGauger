"""Saxo account-truth ledger: read-only broker observation, persistent as-of context.

Account equity is a PRIMARY observable, not synonymous with trading P/L.
A change in TotalValue includes deposits/withdrawals/transfers and cannot be
attributed to one strategy without cash-flow and trade reconciliation.
No broker POST, no account modification, no per-position loss guard here.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from math import isfinite
import json
from threading import Lock
from typing import Any, Mapping

from database import connect

_SCHEMA_LOCK=Lock()
_SCHEMA_READY=False
COLLECTION_SECONDS=300
SOURCE="SAXO_PORTFOLIO_BALANCES_ACCOUNT_KEY"


@dataclass(frozen=True, slots=True)
class SaxoAccountTruthV1:
    account_id: str
    account_name: str
    currency: str
    observed_at: datetime
    total_value: float
    cash_balance: float | None
    unrealized_margin_pnl: float | None
    financing_accruals: float | None
    transactions_not_booked: float | None
    cost_to_close: float | None
    margin_used: float | None
    margin_utilization_pct: float | None
    calculation_reliability: str
    context_json: str = "[]"

    @property
    def verified(self) -> bool:
        return self.calculation_reliability.lower()=="ok"


def _optional_number(data: Mapping, field: str) -> float | None:
    value=data.get(field)
    if value is None:
        return None
    if isinstance(value,bool):
        raise ValueError("SAXO_NUMERIC_FIELD_INVALID")
    number=float(value)
    if not isfinite(number):
        raise ValueError("SAXO_NONFINITE_NUMBER")
    return number


def parse_saxo_balance_v1(*, account: Mapping, payload: Mapping,
                          observed_at: datetime, context: tuple[dict,...]=()) -> SaxoAccountTruthV1:
    """Verify exact account/currency; no default numeric values or FX guesses."""
    if not isinstance(account,Mapping) or not isinstance(payload,Mapping):
        raise ValueError("SAXO_ACCOUNT_OR_BALANCE_MISSING")
    account_id=str(account.get("AccountId") or "").strip()
    key=str(account.get("AccountKey") or "").strip()
    account_currency=str(account.get("Currency") or "").strip().upper()
    response_currency=str(payload.get("Currency") or "").strip().upper()
    if not account_id or not key or not account_currency or response_currency!=account_currency:
        raise ValueError("SAXO_ACCOUNT_CURRENCY_BOUNDARY_UNVERIFIED")
    if isinstance(payload.get("AccountId"),str) and payload["AccountId"]!=account_id:
        raise ValueError("SAXO_RETURNED_ACCOUNT_MISMATCH")
    if not isinstance(observed_at,datetime) or observed_at.tzinfo is None:
        raise ValueError("UTC_OBSERVATION_TIME_REQUIRED")
    total=_optional_number(payload,"TotalValue")
    if total is None:
        raise ValueError("SAXO_TOTAL_VALUE_MISSING")
    margin=payload.get("InitialMargin")
    if margin is not None and not isinstance(margin,Mapping):
        raise ValueError("SAXO_INITIAL_MARGIN_INVALID")
    margin=margin or {}
    reliability=str(payload.get("CalculationReliability") or "Unverified").strip()[:64]
    name=str(account.get("DisplayName") or account.get("AccountName") or account_id).strip()[:128]
    return SaxoAccountTruthV1(
        account_id=account_id,account_name=name,currency=account_currency,
        observed_at=observed_at.astimezone(timezone.utc),
        total_value=total,
        cash_balance=_optional_number(payload,"CashBalance"),
        unrealized_margin_pnl=_optional_number(payload,"UnrealizedMarginProfitLoss"),
        financing_accruals=_optional_number(payload,"FinancingAccruals"),
        transactions_not_booked=_optional_number(payload,"TransactionsNotBooked"),
        cost_to_close=_optional_number(payload,"CostToClosePositions"),
        margin_used=_optional_number(payload,"MarginUsedByCurrentPositions"),
        margin_utilization_pct=_optional_number(payload,"MarginUtilizationPct"),
        calculation_reliability=reliability,
        context_json=json.dumps(context,ensure_ascii=False,sort_keys=True),
    )


def ensure_account_truth_schema_v1(*,db_path="pricegauger.db")->None:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    with _SCHEMA_LOCK:
        if _SCHEMA_READY:
            return
        with connect(db_path) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS pg_saxo_account_truth_v1(
              account_id TEXT NOT NULL,account_name TEXT NOT NULL,
              currency TEXT NOT NULL,slot_utc TEXT NOT NULL,
              observed_at TEXT NOT NULL,source TEXT NOT NULL,
              total_value DOUBLE PRECISION NOT NULL,
              cash_balance DOUBLE PRECISION,
              unrealized_margin_pnl DOUBLE PRECISION,
              financing_accruals DOUBLE PRECISION,
              transactions_not_booked DOUBLE PRECISION,
              cost_to_close DOUBLE PRECISION,margin_used DOUBLE PRECISION,
              margin_utilization_pct DOUBLE PRECISION,
              calculation_reliability TEXT NOT NULL,
              context_json TEXT NOT NULL,
              PRIMARY KEY(account_id,slot_utc)
            )""")
            db.execute("""CREATE INDEX IF NOT EXISTS pg_saxo_account_truth_time_v1
              ON pg_saxo_account_truth_v1(account_id,observed_at DESC)""")
        # Do not memoize SQLite fallback schema across distinct test files.
        from database import using_postgres
        if using_postgres(): _SCHEMA_READY=True


def save_account_truth_v1(snapshot:SaxoAccountTruthV1,*,db_path="pricegauger.db")->bool:
    ensure_account_truth_schema_v1(db_path=db_path)
    date=snapshot.observed_at
    epoch=int(date.timestamp())
    slot=datetime.fromtimestamp((epoch//COLLECTION_SECONDS)*COLLECTION_SECONDS,timezone.utc).isoformat()
    with connect(db_path) as db:
        cursor=db.execute("""INSERT INTO pg_saxo_account_truth_v1(
            account_id,account_name,currency,slot_utc,observed_at,source,
            total_value,cash_balance,unrealized_margin_pnl,financing_accruals,
            transactions_not_booked,cost_to_close,margin_used,
            margin_utilization_pct,calculation_reliability,context_json
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(account_id,slot_utc) DO NOTHING""",(
            snapshot.account_id,snapshot.account_name,snapshot.currency,
            slot,date.isoformat(),SOURCE,snapshot.total_value,snapshot.cash_balance,
            snapshot.unrealized_margin_pnl,snapshot.financing_accruals,
            snapshot.transactions_not_booked,snapshot.cost_to_close,
            snapshot.margin_used,snapshot.margin_utilization_pct,
            snapshot.calculation_reliability,snapshot.context_json,
        ))
        return cursor.rowcount==1


def load_account_truth_v1(*,account_id:str|None=None,days:int=30,
                           db_path="pricegauger.db")->tuple[dict,...]:
    ensure_account_truth_schema_v1(db_path=db_path)
    after=(datetime.now(timezone.utc)-timedelta(days=max(1,min(int(days),180)))).isoformat()
    clause=" AND account_id=?" if account_id else ""
    args=(after,account_id) if account_id else (after,)
    # A filtered account must return its COMPLETE requested history for correct
    # strategy windows (90 days * 288 samples/day is well below 50k).
    # For the fleet overview bound total memory, but fetch the NEWEST rows,
    # not the oldest: otherwise a 30/90-day selection omits today's status.
    ordering="ORDER BY observed_at ASC" if account_id else "ORDER BY observed_at DESC, account_id DESC LIMIT 50000"
    with connect(db_path) as db:
        rows=db.execute("""SELECT account_id,account_name,currency,observed_at,
           total_value,cash_balance,unrealized_margin_pnl,financing_accruals,
           transactions_not_booked,cost_to_close,margin_used,margin_utilization_pct,
           calculation_reliability,context_json,source
           FROM pg_saxo_account_truth_v1 WHERE observed_at>=?"""+clause+" "+ordering,args).fetchall()
    if not account_id:
        rows=reversed(rows)
    keys=("account_id","account_name","currency","observed_at","total_value",
          "cash_balance","unrealized_margin_pnl","financing_accruals",
          "transactions_not_booked","cost_to_close","margin_used",
          "margin_utilization_pct","calculation_reliability","context_json","source")
    return tuple(dict(row) if hasattr(row,"keys") else dict(zip(keys,row)) for row in rows)


def account_value_summary_v1(samples:tuple[dict,...]|list[dict]) -> dict[str,Any]:
    """Never fabricate net P/L from account value minus deposits."""
    valid=[s for s in samples if str(s.get("calculation_reliability") or "").lower()=="ok"]
    if not valid:
        return {"status":"NO_VERIFIED_SAXO_ACCOUNT_VALUES",
                "trading_profit_nok":None,"flow_adjusted_return_pct":None,
                "value_change":None}
    first,last=valid[0],valid[-1]
    if first["currency"]!=last["currency"] or first["account_id"]!=last["account_id"]:
        return {"status":"INCOMPATIBLE_ACCOUNT_CURRENCY",
                "trading_profit_nok":None,"flow_adjusted_return_pct":None,
                "value_change":None}
    delta=float(last["total_value"])-float(first["total_value"])
    return {"status":"CASH_FLOWS_AND_BOOKED_COSTS_NOT_RECONCILED",
            "account_id":last["account_id"],"currency":last["currency"],
            "observed_from":first["observed_at"],"observed_to":last["observed_at"],
            "value_change":delta,"trading_profit_nok":None,
            "flow_adjusted_return_pct":None,"verified_samples":len(valid)}


def _account_strategy_context_v1(*,db_path:str)->dict[str,tuple[dict,...]]:
    """Persist as-of V3 strategy, instrument and market context, not inferred P/L."""
    from autotrader_v3_instance_registry_v1 import load_v3_instances_v1
    from autotrader_v3_config_v1 import load_autotrader_config_v3
    from autotrader_v3_live_authority_v1 import live_authority_armed_v3
    from canonical_market_bars_v2 import CanonicalMarketBarStoreV2
    now=datetime.now(timezone.utc)
    results:dict[str,list[dict]]={}
    for item in load_v3_instances_v1(db_path=db_path):
        config=load_autotrader_config_v3(item.instance_id,db_path=db_path)
        row={"instance_id":item.instance_id,"market":item.market_name,
             "uic":item.uic,"asset_type":item.asset_type,
             "instrument_id":item.instrument_id,
             "strategy":config.strategy_key,"timeframe":config.timeframe,
             "regime_timeframe":config.regime_timeframe,
             "modifiers":list(config.modifiers),
             "live_armed":live_authority_armed_v3(item.instance_id,db_path=db_path),
             "market_bar_at":None,"market_close":None}
        try:
            bars=CanonicalMarketBarStoreV2(db_path).load_instrument_range(
                instrument_id=item.instrument_id,
                start=now-timedelta(minutes=5),end=now,limit=10)
            if bars:
                last=bars[-1]
                when=datetime.fromisoformat(last.bar_time.replace("Z","+00:00"))
                if 0<=(now-when).total_seconds()<=180:
                    row["market_bar_at"]=last.bar_time
                    row["market_close"]=last.close
        except Exception:
            # Missing or delayed market context MUST be reported as unavailable.
            pass
        results.setdefault(item.account_id,[]).append(row)
    return {k:tuple(v) for k,v in results.items()}


def collect_saxo_account_truth_once_v1(*,broker=None,
                                      db_path="pricegauger.db",
                                      now:datetime|None=None)->dict[str,int|str]:
    """Collect every actual Saxo LIVE account; one verified account-key GET each.

    Called only by the slow independent telemetry thread or an explicit
    operator action. No orders, no business decisions, no fake backfill.
    """
    if broker is None:
        from autotrader_v3_live_saxo_v1 import configured_live_pilot_client_v3
        broker=configured_live_pilot_client_v3()
    if broker is None:
        return {"status":"LIVE_SAXO_UNAVAILABLE","seen":0,"saved":0,"failed":0}
    # Collector has its own SaxoClient, never shares the worker's execution client.
    if hasattr(broker,"client") and hasattr(broker.client,"timeout"):
        broker.client.timeout=min(float(broker.client.timeout),5.)
    try:
        accounts=tuple(broker.accounts())
    except Exception:
        return {"status":"ACCOUNTS_GET_FAILED","seen":0,"saved":0,"failed":1}
    try:
        contexts=_account_strategy_context_v1(db_path=db_path)
    except Exception:
        contexts={}  # Unavailable context is NEVER inferred as a strategy match.
    seen=saved=failed=0
    errors:dict[str,int]={}
    def fail(code:str):
        nonlocal failed
        failed+=1
        errors[code]=errors.get(code,0)+1
    _safe_parser_errors={
        "SAXO_ACCOUNT_OR_BALANCE_MISSING","SAXO_ACCOUNT_CURRENCY_BOUNDARY_UNVERIFIED",
        "SAXO_RETURNED_ACCOUNT_MISMATCH","SAXO_TOTAL_VALUE_MISSING",
        "SAXO_NUMERIC_FIELD_INVALID","SAXO_NONFINITE_NUMBER",
        "SAXO_INITIAL_MARGIN_INVALID","UTC_OBSERVATION_TIME_REQUIRED",
    }
    for account in accounts:
        if not isinstance(account,Mapping):
            fail("INVALID_ACCOUNT_ROW")
            continue
        seen+=1
        try:
            identity=str(account["AccountId"]).strip()
            key=str(account["AccountKey"]).strip()
            client_key=str(account["ClientKey"]).strip()
            if not all((identity,key,client_key)):
                fail("ACCOUNT_ID_OR_KEYS_MISSING")
                continue
        except Exception:
            fail("ACCOUNT_ID_OR_KEYS_MISSING")
            continue
        try:
            # Both keys are documented for /port/v1/balances and make the
            # client/account boundary explicit, consistent with Saxo hist/v4.
            payload=broker.client._get("port/v1/balances",params={
                "AccountKey":key,"ClientKey":client_key})
        except Exception as exc:
            status_code=getattr(exc,"status_code",None)
            if isinstance(status_code,int) and 400<=status_code<=599:
                fail(f"SAXO_BALANCES_HTTP_{status_code}")
            else:
                category=str(getattr(exc,"status","") or "").upper()
                fail("SAXO_BALANCES_"+category if category in
                     {"TIMEOUT","CONNECTION_FAILED","TOKEN_MISSING","AUTH_FAILED"}
                     else "SAXO_BALANCES_GET_FAILED")
            continue
        try:
            moment=(now or datetime.now(timezone.utc))
            snapshot=parse_saxo_balance_v1(
                account=account,payload=payload,observed_at=moment,
                context=contexts.get(identity,()))
        except Exception as exc:
            code=str(exc)
            fail(code if code in _safe_parser_errors else "SAXO_BALANCES_PARSE_FAILED")
            continue
        try:
            saved+=int(save_account_truth_v1(snapshot,db_path=db_path))
        except Exception:
            fail("SAXO_ACCOUNT_SNAPSHOT_DB_FAILED")
    return {"status":"OK" if not failed else "PARTIAL",
            "seen":seen,"saved":saved,"failed":failed,
            "errors":dict(sorted(errors.items()))}


__all__=["SaxoAccountTruthV1","parse_saxo_balance_v1",
         "save_account_truth_v1","load_account_truth_v1",
         "account_value_summary_v1","collect_saxo_account_truth_once_v1",
         "COLLECTION_SECONDS"]
