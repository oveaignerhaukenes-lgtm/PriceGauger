from autotrader_v3_domain import AccountBoundaryV3, TargetInventoryV3
from autotrader_v3_execution_plan_v1 import plan_execution_v3
from autotrader_v3_pipeline_v1 import TraderV3, evaluate_trader_v3


def _plan(actual, target):
    trader=TraderV3('t',AccountBoundaryV3('account',1,'CfdOnIndex'),'macd-histogram-v1')
    snapshot=evaluate_trader_v3(
        trader=trader,
        base_target=TargetInventoryV3(target),
        actual_inventory=TargetInventoryV3(actual),
    ).snapshot
    return plan_execution_v3(snapshot)


def test_oversized_same_side_manual_position_is_reduced_to_target():
    plan=_plan(0.12,0.03)
    mutation=next(step for step in plan.steps if step.action in {'REDUCE','CLOSE','OPEN','ADD'})
    assert mutation.action == 'REDUCE'
    assert mutation.amount == 0.09


def test_oversized_opposite_side_is_closed_before_any_new_expansion():
    plan=_plan(0.12,-0.03)
    mutation=next(step for step in plan.steps if step.action in {'REDUCE','CLOSE','OPEN','ADD'})
    assert mutation.action == 'CLOSE'
    assert mutation.amount == 0.12
