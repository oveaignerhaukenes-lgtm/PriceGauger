from autotrader_v3_domain import TargetInventoryV3
from autotrader_v3_pipeline_v1 import TraderV3, evaluate_trader_v3
from autotrader_v3_domain import AccountBoundaryV3
from autotrader_v3_reset_on_loss_v1 import ResetOnLossModifierV3, open_pnl_from_net_position_v3


def _trader():
    return TraderV3("t", AccountBoundaryV3("a", 1, "CfdOnIndex"), "macd-stoch-v1")


def test_negative_open_pnl_flattens_long():
    result=evaluate_trader_v3(
        trader=_trader(),base_target=TargetInventoryV3(0.06),
        actual_inventory=TargetInventoryV3(0.06),
        modifiers=(ResetOnLossModifierV3(-0.01,0.06),))
    assert result.snapshot.effective_target.amount == 0.0
    assert result.snapshot.pending_delta == -0.06


def test_negative_open_pnl_flattens_short():
    result=evaluate_trader_v3(
        trader=_trader(),base_target=TargetInventoryV3(-0.06),
        actual_inventory=TargetInventoryV3(-0.06),
        modifiers=(ResetOnLossModifierV3(-0.01,-0.06),))
    assert result.snapshot.effective_target.amount == 0.0
    assert result.snapshot.pending_delta == 0.06


def test_nonnegative_pnl_passes_strategy_target():
    mod=ResetOnLossModifierV3(0.01,0.03)
    target,reason=mod.apply(_trader(),TargetInventoryV3(0.04))
    assert target.amount == 0.04
    assert "pass-through" in reason


def test_flat_inventory_does_not_block_reentry_same_direction():
    mod=ResetOnLossModifierV3(-1.0,0.0)
    target,_=mod.apply(_trader(),TargetInventoryV3(0.01))
    assert target.amount == 0.01


def test_reads_saxo_dynamic_open_pnl():
    row={"NetPositionDynamic":{"OpenProfitLoss":-12.5}}
    assert open_pnl_from_net_position_v3(row) == -12.5
