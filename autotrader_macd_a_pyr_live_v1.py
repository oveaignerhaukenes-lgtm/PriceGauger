"""LIVE adapter for MACD-A-PYR(1-30) on a V2-owned account.

Signal/planner remains V2. Exact lot mutations use the canonical durable V3
order guard and Saxo adapter so V2 and V3 share execution invariants while
retaining separate account/product ownership.
"""
from __future__ import annotations
import json, logging
from datetime import datetime, timezone, timedelta
from uuid import NAMESPACE_URL, uuid5
from database import connect
from canonical_market_bars_v2 import CanonicalMarketBarStoreV2
from autotrader_macd_models_live_v1 import _adaptive_clock_v1, _closed_observations_v1
from autotrader_macd_a_pyr_v1 import Cross, PyramidState, plan_macd_a_pyramid
from autotrader_macd_a_extended_v1 import PYRAMID_STRATEGY_KEY, TIMEFRAMES
from autotrader_v3_live_saxo_v1 import configured_live_pilot_client_v3
from autotrader_v3_order_guard_v1 import reserve, mark, pending_order
from autotrader_v3_position_reconcile_v1 import reconcile_position_v3
from autotrader_strategy_enrollment_v2 import EXECUTION_MODE_LIVE
from saxo_provider import SaxoInstrument
from saxo_trading import SaxoOrderRequest

LOGGER=logging.getLogger("pricegauger.autotrader.v2.macd_a_pyr_live")
LOOKBACK=timedelta(days=4)
MAX_BARS=12000
TRANCHE=0.02
MAX_AMOUNT=0.20

def _schema(db_path):
    with connect(db_path) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS pg_v2_macd_a_pyr_live_state(
          pilot_key TEXT PRIMARY KEY, seen_events TEXT NOT NULL DEFAULT '[]',
          updated_at TEXT NOT NULL)""")

def _seen(pilot_key,db_path):
    _schema(db_path)
    with connect(db_path) as db:
        row=db.execute("SELECT seen_events FROM pg_v2_macd_a_pyr_live_state WHERE pilot_key=?",(pilot_key,)).fetchone()
    if row is None:return frozenset()
    raw=row["seen_events"] if isinstance(row,dict) else row[0]
    return frozenset(json.loads(str(raw)))

def _save_seen(pilot_key,seen,db_path):
    _schema(db_path)
    payload=json.dumps(sorted(seen))
    with connect(db_path) as db:
        db.execute("""INSERT INTO pg_v2_macd_a_pyr_live_state(pilot_key,seen_events,updated_at)
          VALUES(?,?,CURRENT_TIMESTAMP) ON CONFLICT(pilot_key) DO UPDATE SET
          seen_events=excluded.seen_events,updated_at=excluded.updated_at""",(pilot_key,payload))

def _crosses(bars,market):
    out=[]
    for minutes in TIMEFRAMES:
        try:
            _,obs=_closed_observations_v1(bars,market_name=market,timeframe_minutes=minutes)
        except ValueError:
            continue
        a,b=obs[-2],obs[-1]
        if (a.spread<=0<b.spread) or (a.spread>=0>b.spread):
            out.append(Cross(minutes,b.closed_at,a.spread,b.spread))
    return tuple(out)

def _actual(e,broker):
    return float(broker.signed_inventory_exact(account_id=e.account_id,uic=int(e.uic),asset_type=e.asset_type))

def _account_context(broker,account_id):
    for row in broker.accounts():
        if isinstance(row,dict) and str(row.get("AccountId") or "")==str(account_id):
            key=str(row.get("AccountKey") or "").strip()
            if key:return key
    raise RuntimeError("V2 LIVE Saxo account unavailable")

def run_macd_a_pyr_extended_live_once_v1(e,*,db_path="pricegauger.db",now=None):
    if not e.enabled or e.execution_mode!=EXECUTION_MODE_LIVE or e.strategy_key!=PYRAMID_STRATEGY_KEY:
        raise ValueError("MACD-A-PYR(1-30) LIVE adapter received wrong enrollment")
    broker=configured_live_pilot_client_v3()
    if broker is None: raise RuntimeError("Saxo LIVE client unavailable")
    actual=_actual(e,broker)
    pending=pending_order(account_id=e.account_id,uic=e.uic,asset_type=e.asset_type,db_path=db_path)
    if pending:
        expected=pending.get("expected_inventory")
        if expected is None:return "PENDING_INVALID"
        rec=reconcile_position_v3(expected_inventory=float(expected),
            submitted_amount=pending.get("submitted_amount"),submitted_side=pending.get("submitted_side"),
            actual_inventory=actual)
        if rec.state=="CONFIRMED":
            mark(request_key=pending["request_key"],state="RECONCILED",detail="V2 pyramid exact inventory confirmed",db_path=db_path)
            return "RECONCILED"
        if rec.state=="WAIT": return "PENDING"
        from manual_saxo_trade_markers_v1 import manual_fill_explains_inventory_change_v1
        amt=float(pending.get("submitted_amount") or 0); side=str(pending.get("submitted_side") or "").lower()
        before=float(expected)-amt if side=="buy" else float(expected)+amt
        if manual_fill_explains_inventory_change_v1(account_id=e.account_id,uic=int(e.uic),asset_type=e.asset_type,
            submitted_at=pending.get("updated_at"),before_inventory=before,actual_inventory=actual):
            mark(request_key=pending["request_key"],state="RECONCILED",detail="Manual Saxo adjustment adopted",db_path=db_path)
            return "MANUAL_ADOPTED"
        return "CONFLICT"

    end=now or datetime.now(timezone.utc)
    bars=tuple(CanonicalMarketBarStoreV2(db_path).load_instrument_range(
        instrument_id=int(e.instrument_id),start=end-LOOKBACK,end=end,limit=MAX_BARS))
    if not bars: raise ValueError("MACD-A-PYR LIVE has no canonical history")
    clock,_,_,_=_adaptive_clock_v1(bars,market_name=e.market_name)
    direction="LONG" if clock.current_spread>0 else "SHORT" if clock.current_spread<0 else "FLAT"
    observed="LONG" if actual>0 else "SHORT" if actual<0 else "FLAT"
    seen=_seen(e.pilot_key,db_path)
    tranches=int(round(abs(actual)/TRANCHE)) if observed!="FLAT" else 0
    state=PyramidState(direction=observed,tranches=tranches,seen_events=seen)
    decision=plan_macd_a_pyramid(state=state,macd_a_direction=direction,observed_direction=observed,
        crosses=_crosses(bars,e.market_name),tranche_amount=TRANCHE,max_amount=MAX_AMOUNT,
        enabled_timeframes=TIMEFRAMES)
    if decision.action=="HOLD": return "HOLD"
    if decision.action=="CLOSE":
        amount=abs(actual)
        if amount<0.01:return "FLAT"
        side="Sell" if actual>0 else "Buy"
    else:
        amount=TRANCHE
        side="Buy" if decision.direction=="LONG" else "Sell"
    account_key=_account_context(broker,e.account_id)
    instrument=SaxoInstrument(asset=e.market_name,uic=int(e.uic),asset_type=e.asset_type)
    request_key=str(uuid5(NAMESPACE_URL,f"v2-pyr:{e.pilot_key}:{decision.reason}:{decision.action}:{actual:.10g}:{amount:.10g}"))
    signed=amount if side=="Buy" else -amount
    order=SaxoOrderRequest(account_key=account_key,instrument=instrument,amount=amount,buy_sell=side,
        external_reference=("pgv2p-"+request_key)[-50:])
    pre=broker.precheck(order)
    if str(pre.get("PreCheckResult") or pre.get("Result") or "").lower() not in {"ok","passed","success"}:
        raise RuntimeError("V2 pyramid Saxo precheck rejected")
    reserve(request_key=request_key,trader_id=e.pilot_key,account_id=e.account_id,uic=e.uic,
        asset_type=e.asset_type,expected_inventory=actual+signed,submitted_amount=amount,
        submitted_side=side,db_path=db_path)
    # Consume the planner event before POST. UNKNOWN therefore cannot replay it.
    _save_seen(e.pilot_key,decision.state.seen_events,db_path)
    mark(request_key=request_key,state="SUBMITTING",db_path=db_path)
    try:
        result=broker.place_order(order,confirm_live=True)
    except Exception as exc:
        mark(request_key=request_key,state="UNKNOWN",detail=f"{type(exc).__name__}: {exc}",db_path=db_path)
        raise
    oid=str(result.get("OrderId") or "").strip() if isinstance(result,dict) else ""
    if not oid:
        mark(request_key=request_key,state="UNKNOWN",detail="Saxo response lacks OrderId",db_path=db_path)
        return "UNKNOWN"
    mark(request_key=request_key,state="SUBMITTED",broker_order_id=oid,db_path=db_path)
    LOGGER.warning("V2 PYR LIVE executed pilot=%s action=%s side=%s amount=%s",e.pilot_key,decision.action,side,amount)
    return f"{decision.action}:{side}:{amount:g}"

__all__=["run_macd_a_pyr_extended_live_once_v1"]
