from autotrader_v3_domain import AccountBoundaryV3, CapitalAllocationV3, ControlModeV3, DecisionSnapshotV3, TargetInventoryV3
from autotrader_v3_execution_plan_v1 import plan_execution_v3


def _snap(actual, target):
    return DecisionSnapshotV3(
        trader_id="t1", account=AccountBoundaryV3("a", 1, "CfdOnIndex"),
        mode=ControlModeV3.DETERMINISTIC, strategy_key="macd-trailing-v1",
        capital_allocation=CapitalAllocationV3(10),
        base_target=TargetInventoryV3(target), effective_target=TargetInventoryV3(target),
        risk_approved_target=TargetInventoryV3(target), actual_inventory=TargetInventoryV3(actual),
        pending_delta=target-actual,
    )


def test_add_same_side_is_only_delta():
    p=plan_execution_v3(_snap(.02,.04))
    assert [(x.action,x.amount,x.direction) for x in p.steps] == [("ADD",.02,"LONG")]


def test_reduce_same_side_is_only_delta():
    p=plan_execution_v3(_snap(.05,.02))
    assert [(x.action,round(x.amount,6),x.direction) for x in p.steps] == [("REDUCE",.03,"LONG")]


def test_hard_reversal_flat_target_closes_all():
    p=plan_execution_v3(_snap(.05,0))
    assert [(x.action,x.amount) for x in p.steps] == [("CLOSE",.05)]


def test_opposite_target_requires_close_confirm_flat_open():
    p=plan_execution_v3(_snap(.03,-.02))
    assert [x.action for x in p.steps] == ["CLOSE","CONFIRM_FLAT","OPEN"]
    assert p.steps[0].requires_flat_confirmation
    assert p.steps[1].requires_flat_confirmation


def test_no_change_is_hold():
    assert plan_execution_v3(_snap(.02,.02)).steps == ()
