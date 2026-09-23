from __future__ import annotations
from dataclasses import dataclass
from autotrader_strategy_enrollment_v2 import StrategyEnrollmentV2,EXECUTION_MODE_LIVE
from autotrader_v3_live_authority_v1 import live_authority_armed_v3
from autotrader_v3_macd_trailing_v1 import STRATEGY_KEY_V3
from autotrader_v3_sim_authority_v1 import sim_authority_armed_v3

@dataclass(frozen=True,slots=True)
class LiveReadinessV3:
    ready:bool
    reasons:tuple[str,...]

def live_readiness_v3(enrollment:StrategyEnrollmentV2, *, broker_is_live:bool, exact_inventory:float, db_path="pricegauger.db")->LiveReadinessV3:
    reasons=[]
    if enrollment.strategy_key!=STRATEGY_KEY_V3: reasons.append("strategy is not MACD-Trailing v3")
    if enrollment.execution_mode!=EXECUTION_MODE_LIVE: reasons.append("enrollment is not LIVE_MANAGE")
    if not enrollment.enabled: reasons.append("enrollment disabled")
    if not broker_is_live: reasons.append("Saxo environment is not LIVE")
    if sim_authority_armed_v3(enrollment.pilot_key,db_path=db_path): reasons.append("simulator authority still armed")
    if not live_authority_armed_v3(enrollment.pilot_key,db_path=db_path): reasons.append("LIVE authority not armed")
    if abs(float(exact_inventory))>1e-12: reasons.append("pilot requires exact Saxo boundary FLAT at activation")
    return LiveReadinessV3(not reasons,tuple(reasons))
