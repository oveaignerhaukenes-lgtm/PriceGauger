def test_three_trader_tv_module_imports():
    from tradingdesk_ui.charts.lightweight.three_trader_tv_v1 import _THREE_TRADER_TV_JS
    assert "LightweightCharts" in _THREE_TRADER_TV_JS
