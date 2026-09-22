from __future__ import annotations

from types import SimpleNamespace

import pytest

from autotrader_v3_domain import AccountBoundaryV3, CapitalAllocationV3, ControlModeV3, DecisionSnapshotV3, TargetInventoryV3, signed_inventory_v3
from autotrader_v3_read_model_v1 import observe_v2_as_v3_v1


def _enrollment():
    return SimpleNamespace(
        pilot_key="pilot-1", strategy_key="macd-a-v1", account_id="acct-1",
        uic=42, asset_type="CfdOnIndex",
    )


def _observation(direction="Buy", amount=0.03):
    return SimpleNamespace(
        account_id="acct-1", net_position_id="np-1", uic=42,
        asset_type="CfdOnIndex", direction=direction, amount=amount,
    )


def test_inventory_is_signed_and_delta_is_target_minus_actual():
    assert signed_inventory_v3(direction="Buy", amount=0.03).amount == pytest.approx(0.03)
    assert signed_inventory_v3(direction="Sell", amount=0.03).amount == pytest.approx(-0.03)
    assert TargetInventoryV3(0.07).delta_from(0.03) == pytest.approx(0.04)


def test_decision_snapshot_rejects_incoherent_pending_delta():
    boundary = AccountBoundaryV3("acct-1", 42, "CfdOnIndex")
    with pytest.raises(ValueError, match="pending_delta"):
        DecisionSnapshotV3(
            trader_id="t", account=boundary, mode=ControlModeV3.DETERMINISTIC,
            strategy_key="s", capital_allocation=CapitalAllocationV3(50), base_target=TargetInventoryV3(0.02),
            effective_target=TargetInventoryV3(0.02),
            risk_approved_target=TargetInventoryV3(0.02),
            actual_inventory=TargetInventoryV3(0.01), pending_delta=0.0,
        )


def test_v2_bridge_is_read_only_and_adopts_actual_inventory_as_all_targets():
    snap = observe_v2_as_v3_v1(_enrollment(), (_observation(),))
    assert snap.account == AccountBoundaryV3("acct-1", 42, "CfdOnIndex")
    assert snap.actual_inventory.amount == pytest.approx(0.03)
    assert snap.base_target == snap.effective_target == snap.risk_approved_target
    assert snap.pending_delta == 0.0


def test_v2_bridge_represents_no_position_as_flat():
    snap = observe_v2_as_v3_v1(_enrollment(), ())
    assert snap.actual_inventory.direction == "FLAT"
    assert snap.pending_delta == 0.0


def test_v2_bridge_fails_closed_on_ambiguous_exact_product():
    with pytest.raises(RuntimeError, match="multiple Saxo positions"):
        observe_v2_as_v3_v1(_enrollment(), (_observation(), _observation(amount=0.01)))


def test_capital_allocation_is_simple_percent_of_account_equity():
    allocation = CapitalAllocationV3(35)
    assert allocation.fraction == pytest.approx(0.35)
    assert allocation.tradeable_equity(1000) == pytest.approx(350)


@pytest.mark.parametrize("pct", [-0.01, 100.01])
def test_capital_allocation_rejects_percent_outside_account(pct):
    with pytest.raises(ValueError, match="between 0 and 100"):
        CapitalAllocationV3(pct)


def test_v2_bridge_defaults_to_full_dedicated_account_allocation():
    snap = observe_v2_as_v3_v1(_enrollment(), ())
    assert snap.capital_allocation.tradeable_pct == pytest.approx(100.0)
