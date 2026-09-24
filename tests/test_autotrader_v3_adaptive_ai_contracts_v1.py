from datetime import datetime, timedelta, timezone

from autotrader_v3_ai_modes_v1 import GodModeDecisionV3, OverseerDecisionV3, god_mode_target_v3
from autotrader_v3_domain import TargetInventoryV3
from autotrader_v3_sim_adapt_v1 import SimAdaptPolicyV3, SimAdaptStateV3, SimCandidateV3, select_sim_candidate_v3


def test_sim_adapt_requires_evidence_and_hysteresis():
    policy=SimAdaptPolicyV3(min_observations=10,switch_margin=.10,cooldown_seconds=0)
    state=SimAdaptStateV3("a", datetime(2026,1,1,tzinfo=timezone.utc))
    close=(SimCandidateV3("a",1.0,20),SimCandidateV3("b",1.05,20))
    assert select_sim_candidate_v3(close,state,policy=policy,now=datetime(2026,1,2,tzinfo=timezone.utc)).selected_key=="a"
    clear=(SimCandidateV3("a",1.0,20),SimCandidateV3("b",1.2,20))
    result=select_sim_candidate_v3(clear,state,policy=policy,now=datetime(2026,1,2,tzinfo=timezone.utc))
    assert result.selected_key=="b" and result.switched


def test_god_mode_outputs_target_not_order_and_expires_to_flat():
    now=datetime(2026,1,1,tzinfo=timezone.utc)
    decision=GodModeDecisionV3(TargetInventoryV3(-.2),.8,"broad state favors short",now+timedelta(minutes=1))
    assert god_mode_target_v3(decision,now=now).amount == -.2
    assert god_mode_target_v3(decision,now=now+timedelta(minutes=2)).amount == 0


def test_overseer_contract_selects_configuration():
    decision=OverseerDecisionV3("macd","Adaptiv",("whipsaw","regime"),.7,"regime selection")
    assert decision.timeframe=="Adaptiv"
