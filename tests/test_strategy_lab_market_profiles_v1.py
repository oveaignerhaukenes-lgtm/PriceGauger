from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def test_research_lab_has_three_distinct_market_strategies() -> None:
    store=(ROOT/"research_strategy_store_v1.py").read_text(encoding="utf-8")
    page=(ROOT/"pages/0_Strategy_Lab.py").read_text(encoding="utf-8")
    for key in ("gold-fed-rates","silver-fed-industry-supply","oil-balance-resupply"):
        assert key in store
    assert "Sølv + Fed/industri/tilbud" in page
    assert "Olje + balanse/resupply" in page

def test_factor_sets_are_strategy_specific_and_oil_cross_factor_exists() -> None:
    source=(ROOT/"strategy_factor_store_v1.py").read_text(encoding="utf-8")
    assert "GOLD_FACTOR_DEFAULTS" in source
    assert "SILVER_FACTOR_DEFAULTS" in source
    assert "OIL_FACTOR_DEFAULTS" in source
    assert source.count('"oil_inflation"') >= 2
    assert '"strategic_reserves"' in source
    assert '"curve_spreads"' in source

def test_strategy_page_uses_selected_strategy_for_memory_and_plans() -> None:
    page=(ROOT/"pages/0_Strategy_Lab.py").read_text(encoding="utf-8")
    assert "load_research_events_v1(strategy)" in page
    assert "load_strategy_factors_v1(strategy)" in page
    assert "load_strategy_messages_v1(strategy)" in page
    assert "load_research_trade_plans_v1(strategy)" in page
