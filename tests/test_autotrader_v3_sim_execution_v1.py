import pytest
from autotrader_v3_domain import AccountBoundaryV3,CapitalAllocationV3,ControlModeV3,DecisionSnapshotV3,TargetInventoryV3
from autotrader_v3_execution_plan_v1 import plan_execution_v3
from autotrader_v3_sim_execution_v1 import build_execution_intent_v3,execute_first_test_step_v3
from saxo_provider import SaxoInstrument
from saxo_trading import SaxoTradingSafetyError

class Trading:
    def __init__(self): self.calls=0
    def precheck(self,o): return {"PreCheckResult":"Ok"}
    def place_order(self,o,confirm_sim=False): assert confirm_sim; self.calls+=1; return {"OrderId":"1"}
    def net_positions_me(self,**kw): return ()

def snap(a,t):
    return DecisionSnapshotV3("t",AccountBoundaryV3("A",7,"CfdOnIndex"),ControlModeV3.DETERMINISTIC,"macd-trailing-v1",CapitalAllocationV3(5),TargetInventoryV3(t),TargetInventoryV3(t),TargetInventoryV3(t),TargetInventoryV3(a),t-a)

def instrument(): return SaxoInstrument(asset="X",uic=7,asset_type="CfdOnIndex",symbol="X",description="X")

def test_first_test_executes_exactly_one_point_zero_one_once():
    s=snap(0,.01); step=plan_execution_v3(s).steps[0]
    intent=build_execution_intent_v3(snapshot=s,step=step,account_key="K",account_id="A",instrument=instrument(),decision_key="bar-1")
    sent=set(); trading=Trading()
    execute_first_test_step_v3(trading=trading,intent=intent,submitted_intent_ids=sent)
    assert trading.calls==1
    with pytest.raises(SaxoTradingSafetyError): execute_first_test_step_v3(trading=trading,intent=intent,submitted_intent_ids=sent)

def test_first_test_rejects_larger_mutation():
    s=snap(0,.02); step=plan_execution_v3(s).steps[0]
    intent=build_execution_intent_v3(snapshot=s,step=step,account_key="K",account_id="A",instrument=instrument(),decision_key="bar-1")
    with pytest.raises(SaxoTradingSafetyError): execute_first_test_step_v3(trading=Trading(),intent=intent,submitted_intent_ids=set())

def test_decision_key_makes_intent_stable():
    s=snap(0,.01); step=plan_execution_v3(s).steps[0]
    a=build_execution_intent_v3(snapshot=s,step=step,account_key="K",account_id="A",instrument=instrument(),decision_key="2026-09-23T00:00Z")
    b=build_execution_intent_v3(snapshot=s,step=step,account_key="K",account_id="A",instrument=instrument(),decision_key="2026-09-23T00:00Z")
    assert a.intent_id==b.intent_id
