from pathlib import Path


def test_three_trader_lab_mounts_three_distinct_models_without_execution_authority():
    source = Path("tradingdesk_three_trader_lab_v1.py").read_text(encoding="utf-8")
    assert 'RULE_NAME = "Dum MACD"' in source
    assert 'ADAPTIVE_NAME = "MACD-adaptiv"' in source
    assert 'HOLISTIC_NAME = "Holistisk AI"' in source
    assert '"TARGET_MACD-A"' in source
    assert "pg_v2_autotrader_ai_baseline_samples" in source
    assert "replay_macd_supervisor_v1" in source
    assert "st.plotly_chart" in source
    assert "send order" not in source.lower()
    assert "saxo" not in source.lower()


def test_three_trader_lab_is_mounted_before_deeper_strategy_labs():
    source = Path("tradingdesk_automanage_panel_v2.py").read_text(encoding="utf-8")
    three = source.index("render_tradingdesk_three_trader_lab_v1(context)")
    supervisor = source.index("render_tradingdesk_macd_supervisor_lab_v1(context)")
    assert three < supervisor
