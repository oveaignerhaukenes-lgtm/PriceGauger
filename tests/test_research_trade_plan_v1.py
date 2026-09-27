from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def test_trade_plan_is_research_only() -> None:
    page=(ROOT/"pages/0_Strategy_Lab.py").read_text(encoding="utf-8")
    assert "Trade Plan" in page
    assert "DRAFT-plan" in page
    assert "Denne versjonen kan ikke handle." in page

def test_trade_plan_contract_has_predictability_controls() -> None:
    source=(ROOT/"research_trade_plan_store_v1.py").read_text(encoding="utf-8")
    for field in ("probability_pct","stop_loss_pct","trail_activation_pct","trailing_distance_pct","event_policy"):
        assert field in source
