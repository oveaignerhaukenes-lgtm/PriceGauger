from __future__ import annotations
import logging
from datetime import datetime,timedelta,timezone
from autotrader_mtf_entry_shadow_v2 import closed_bars_v2,macd_observations_v2
from autotrader_risk_control_v2 import _position_observations_v2
from autotrader_strategy_enrollment_v2 import load_active_strategy_enrollments_v2,EXECUTION_MODE_LIVE
from autotrader_v3_closed_bar_driver_v1 import evaluate_closed_bar_once_v3
from autotrader_v3_domain import AccountBoundaryV3,TargetInventoryV3,signed_inventory_v3
from autotrader_v3_execution_plan_v1 import plan_execution_v3
from autotrader_v3_live_authority_v1 import live_authority_armed_v3
from autotrader_v3_live_saxo_v1 import configured_live_pilot_client_v3
from autotrader_v3_macd_trailing_v1 import STRATEGY_KEY_V3
from autotrader_v3_pipeline_v1 import TraderV3,evaluate_trader_v3
from canonical_market_bars_v2 import CanonicalMarketBarStoreV2
from saxo_provider import SaxoInstrument
from saxo_trading import SaxoOrderRequest

LOGGER=logging.getLogger("pricegauger.autotrader.v3.live")

def _actual(e,observations):
    matches=[o for o in observations if o.account_id==e.account_id and int(o.uic)==int(e.uic) and o.asset_type==e.asset_type]
    if len(matches)>1: raise RuntimeError("ambiguous exact v3 Saxo boundary")
    return TargetInventoryV3(0) if not matches else signed_inventory_v3(direction=matches[0].direction,amount=matches[0].amount)

def run_v3_live_cycle_v1(*,db_path="pricegauger.db",now=None)->int:
    """Normal v3 LIVE runtime. The LIVE toggle is the user authority boundary."""
    enrollments=tuple(e for e in load_active_strategy_enrollments_v2()
        if e.strategy_key==STRATEGY_KEY_V3 and e.execution_mode==EXECUTION_MODE_LIVE
        and live_authority_armed_v3(e.pilot_key,db_path=db_path))
    if not enrollments: return 0
    broker=configured_live_pilot_client_v3()
    if broker is None: raise RuntimeError("v3 LIVE is armed but Saxo LIVE client is unavailable")
    observations=_position_observations_v2(broker.client)
    accounts={a.account_id:a for a in broker.accounts()}
    executed=0; end=now or datetime.now(timezone.utc)
    for e in enrollments:
        actual=_actual(e,observations)
        bars=CanonicalMarketBarStoreV2(db_path).load_instrument_range(instrument_id=e.instrument_id,start=end-timedelta(days=14),end=end,limit=20000)
        closed=closed_bars_v2(tuple(b.point for b in bars),market=e.market_name,timeframe_minutes=5) if bars else ()
        obs=macd_observations_v2(closed,timeframe_minutes=5) if closed else ()
        if not obs: continue
        decision=evaluate_closed_bar_once_v3(trader_id=e.pilot_key,observation=obs[-1],db_path=db_path)
        trader=TraderV3(e.pilot_key,AccountBoundaryV3(e.account_id,int(e.uic),e.asset_type),e.strategy_key)
        snapshot=evaluate_trader_v3(trader=trader,base_target=decision.decision.target,actual_inventory=actual).snapshot
        plan=plan_execution_v3(snapshot)
        mutation=next((s for s in plan.steps if s.action in {"OPEN","ADD","REDUCE","CLOSE"}),None)
        if mutation is None: continue
        account=accounts.get(e.account_id)
        if account is None: raise RuntimeError(f"v3 LIVE account unavailable: {e.account_id}")
        side=("Buy" if mutation.direction=="LONG" else "Sell")
        if mutation.action in {"REDUCE","CLOSE"}: side=("Sell" if mutation.direction=="LONG" else "Buy")
        instrument=SaxoInstrument(asset=e.market_name,uic=int(e.uic),asset_type=e.asset_type)
        order=SaxoOrderRequest(account_key=account.account_key,instrument=instrument,amount=mutation.amount,buy_sell=side,
            external_reference=("pgv3-"+decision.decision_key)[-50:])
        pre=broker.precheck(order)
        if str(pre.get("PreCheckResult") or pre.get("Result") or "").lower() not in {"ok","passed","success"}:
            raise RuntimeError(f"v3 LIVE precheck rejected: {pre}")
        broker.place_order(order,confirm_live=True); executed+=1
        LOGGER.warning("v3 LIVE executed trader=%s step=%s side=%s amount=%s",e.pilot_key,mutation.action,side,mutation.amount)
    return executed
