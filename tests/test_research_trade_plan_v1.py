from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def test_trade_plan_is_research_only() -> None:
    page=(ROOT/"pages/0_Strategy_Lab.py").read_text(encoding="utf-8")
    assert "Trade Plan" in page
    assert "DRAFT-plan" in page
    assert "ingen direkte broker-POST authority" in page

def test_trade_plan_contract_has_predictability_controls() -> None:
    source=(ROOT/"research_trade_plan_store_v1.py").read_text(encoding="utf-8")
    for field in ("probability_pct","stop_loss_pct","trail_activation_pct","trailing_distance_pct","event_policy"):
        assert field in source


def test_trade_plan_requires_explicit_approval_before_execution_handoff() -> None:
    page=(ROOT/"pages/0_Strategy_Lab.py").read_text(encoding="utf-8")
    store=(ROOT/"research_trade_plan_store_v1.py").read_text(encoding="utf-8")
    assert "Godkjenn Execution Plan" in page
    assert "approve_research_trade_plan_v1" in page
    assert "pg_v2_research_execution_handoffs" in store
    assert '"APPROVED"' in store
    assert "broker execution remains downstream" in store


def test_strategy_lab_budget_and_controls_are_scope_bound() -> None:
    page=(ROOT/"pages/0_Strategy_Lab.py").read_text(encoding="utf-8")
    assert "budget_nok=budget_nok" in page
    assert "exposure_pct=exposure_pct" in page
    assert "scope_id=handoff.scope_id" in page
    assert "strategy_key=strategy" in page
    assert "strategy_key=key" not in page
    assert "from research_trade_plan_store_v1 import (\\\\n" not in page
