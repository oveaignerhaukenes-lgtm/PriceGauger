from types import SimpleNamespace

import autotrader_v2_vnext_shadow_v1 as shadow


def test_shadow_returns_plan_without_execution(monkeypatch):
    monkeypatch.setattr(shadow, "execution_readiness_v2_vnext_v1", lambda enrollment, db_path: SimpleNamespace(ready=True, status="READY", detail="ok"))
    result = shadow.shadow_plan_v2_vnext_v1(
        SimpleNamespace(), actual_inventory=0, desired_inventory=-0.02,
        amount_step=0.01, db_path="ignored")
    assert result.status == "READY"
    assert result.mutation.action == "OPEN"
    assert result.mutation.side == "Sell"
    assert result.mutation.amount == 0.02
