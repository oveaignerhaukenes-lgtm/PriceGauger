from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def test_silver_factor_configuration_is_persistent_and_explicit() -> None:
    source=(ROOT/"strategy_factor_store_v1.py").read_text(encoding="utf-8")
    for key in ("industrial_demand","mine_supply","byproduct_supply","inventories_flows","gold_silver_ratio"):
        assert key in source
    assert "pg_v2_strategy_factors" in source

def test_factor_configuration_reaches_strategy_ai() -> None:
    source=(ROOT/"strategy_discussion_ai_v1.py").read_text(encoding="utf-8")
    page=(ROOT/"pages/0_Strategy_Lab.py").read_text(encoding="utf-8")
    assert "factor_configuration" in source
    assert "Vurderingsfaktorer" in page
    assert ".toggle(" in page
