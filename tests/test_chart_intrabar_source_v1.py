from pathlib import Path

def test_live_chart_does_not_depend_on_closed_canonical_bar_for_intrabar_motion():
    page=Path("pages/0_TradingDesk.py").read_text(encoding="utf-8")
    assert "forming = _forming_chart_candle(context)" in page
    renderer=Path("tradingdesk_ui/charts/lightweight/simple_live_v2.py").read_text(encoding="utf-8")
    assert "entry.candles.update" in renderer
    assert "payload.forming_candle || null" in renderer
