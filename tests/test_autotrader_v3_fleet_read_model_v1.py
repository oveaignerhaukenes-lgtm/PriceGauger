from __future__ import annotations

from types import SimpleNamespace

from autotrader_v3_fleet_read_model_v1 import build_fleet_read_model_v3


def _enrollment(*, pilot="p1", enabled=True, uic=42):
    return SimpleNamespace(
        pilot_key=pilot, strategy_key="macd-a-v1", account_id="acct-1",
        uic=uic, asset_type="CfdOnIndex", enabled=enabled, execution_mode="LIVE",
    )


def _observation(*, uic=42, direction="Buy", amount=0.03):
    return SimpleNamespace(
        account_id="acct-1", net_position_id="np", uic=uic,
        asset_type="CfdOnIndex", direction=direction, amount=amount,
    )


def test_fleet_truth_line_exposes_entire_target_chain():
    rows = build_fleet_read_model_v3((_enrollment(),), (_observation(),))
    assert len(rows) == 1
    line = rows[0].truth_line
    assert "kapital 100%" in line
    assert "base +0.03" in line
    assert "effektiv +0.03" in line
    assert "risk +0.03" in line
    assert "Saxo +0.03" in line
    assert "pending +0.00" in line


def test_fleet_deduplicates_migration_history_by_exact_account_product_boundary():
    rows = build_fleet_read_model_v3(
        (_enrollment(pilot="new"), _enrollment(pilot="old", enabled=False)),
        (_observation(),),
    )
    assert len(rows) == 1
    assert rows[0].snapshot.trader_id == "new"
