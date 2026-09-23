from pathlib import Path

def test_chart_prefers_canonical_refresh_without_forming_overlay():
    page=Path("pages/0_TradingDesk.py").read_text(encoding="utf-8")
    assert "TRADINGDESK_PAGE_REFRESH_SECONDS = 2" in page
    assert "forming = _forming_chart_candle(context)" in page

def test_v3_ui_distinguishes_armed_from_managing():
    ui=Path("tradingdesk_automanager_simple_v1.py").read_text(encoding="utf-8")
    assert "NOT MANAGING / ingen worker-heartbeat" in ui
    assert "LIVE MANAGING" in ui

def test_v3_runtime_persists_management_heartbeat():
    runtime=Path("autotrader_v3_live_runtime_v1.py").read_text(encoding="utf-8")
    assert "autotrader_v3_live_runtime_state" in runtime
    assert '"MANAGING"' in runtime
