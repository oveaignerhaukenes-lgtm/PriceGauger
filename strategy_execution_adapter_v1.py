from __future__ import annotations
from dataclasses import dataclass
import json
from autotrader_strategy_enrollment_v2 import EXECUTION_MODE_LIVE,load_strategy_enrollment_v2
from research_trade_plan_store_v1 import assert_research_scope_v1
from strategy_execution_scope_v1 import ExecutionAdapterScopeV1

@dataclass(frozen=True,slots=True)
class StrategyExecutionBindingV1:
    scope:ExecutionAdapterScopeV1
    execution_strategy_key:str

def validate_strategy_execution_binding_v1(*,scope_id:str,strategy_key:str,plan_id:str,handoff_id:str,
 pilot_key:str,account_id:str,uic:int,asset_type:str,budget_nok:float,exposure_pct:float)->StrategyExecutionBindingV1:
    """Resolve an exact existing LIVE controller; never infer by display/instrument name."""
    handoff=assert_research_scope_v1(plan_id=plan_id,strategy_key=strategy_key,scope_id=scope_id)
    if handoff.handoff_id!=handoff_id or handoff.status not in {"APPROVED","QUEUED"}:
        raise ValueError("EXECUTION_HANDOFF_IDENTITY_MISMATCH")
    payload=json.loads(handoff.payload_json)
    if (payload.get("plan_id")!=plan_id or payload.get("strategy_key")!=strategy_key
        or payload.get("scope_id")!=scope_id or float(payload.get("budget_nok",-1))!=float(budget_nok)
        or float(payload.get("exposure_pct",-1))!=float(exposure_pct)):
        raise ValueError("EXECUTION_HANDOFF_SNAPSHOT_MISMATCH")
    enrollment=load_strategy_enrollment_v2(pilot_key)
    if enrollment is None or not enrollment.enabled or enrollment.execution_mode!=EXECUTION_MODE_LIVE:
        raise ValueError("EXECUTION_PILOT_NOT_ACTIVE_LIVE")
    if enrollment.account_id!=account_id or int(enrollment.uic)!=int(uic) or enrollment.asset_type!=asset_type:
        raise ValueError("EXECUTION_PRODUCT_BOUNDARY_MISMATCH")
    scope=ExecutionAdapterScopeV1(scope_id=scope_id,strategy_key=strategy_key,plan_id=plan_id,
      handoff_id=handoff_id,pilot_key=pilot_key,account_id=account_id,uic=int(uic),asset_type=asset_type,
      budget_nok=float(budget_nok),exposure_pct=float(exposure_pct))
    return StrategyExecutionBindingV1(scope=scope,execution_strategy_key=enrollment.strategy_key)

def live_open_budget_supported_v1(binding:StrategyExecutionBindingV1)->bool:
    """False until Strategy Lab budget is carried into the canonical OPEN sizing/precheck path."""
    return False

def require_live_open_budget_support_v1(binding:StrategyExecutionBindingV1)->None:
    if not live_open_budget_supported_v1(binding):
        raise ValueError("STRATEGY_LAB_LIVE_OPEN_BLOCKED_BUDGET_NOT_END_TO_END")
