from pathlib import Path

from autotrader_v3_domain import TargetInventoryV3
from autotrader_v3_reset_on_loss_v1 import ResetOnLossModifierV3


def test_reset_on_loss_is_inert_when_flat():
    modifier=ResetOnLossModifierV3(open_pnl=0.0,actual_inventory=0.0)
    target,detail=modifier.apply(None,TargetInventoryV3(0.02))
    assert target.amount == 0.02
    assert "inactive" in detail


def test_reset_on_loss_flattens_losing_open_position():
    modifier=ResetOnLossModifierV3(open_pnl=-1.0,actual_inventory=0.02)
    target,_=modifier.apply(None,TargetInventoryV3(0.03))
    assert target.amount == 0.0


def test_live_runtime_skips_saxo_pnl_query_for_flat_inventory():
    source=Path("autotrader_v3_live_runtime_v1.py").read_text(encoding="utf-8")
    flat=source.index("if abs(actual.amount) <= 1e-12:")
    query=source.index("open_pnl=broker.open_pnl_exact",flat)
    otherwise=source.index("else:",flat)
    assert flat < otherwise < query
