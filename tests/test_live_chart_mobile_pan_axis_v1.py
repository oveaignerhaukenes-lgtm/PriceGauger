from pathlib import Path

def test_live_chart_mobile_pan_and_axis_scale_are_enabled():
    source=Path("tradingdesk_ui/charts/lightweight/simple_live_v2.py").read_text(encoding="utf-8")
    assert "touchAction: 'none'" in source
    assert "horzTouchDrag: true, vertTouchDrag: true" in source
    assert "axisPressedMouseMove: {{ time: true, price: true }}" in source
    assert "axisDoubleClickReset: {{ time: true, price: true }}" in source
    assert "if (candleData.length) chart.timeScale().fitContent();" in source
    # Existing chart instance is updated without resetting the user's view.
    assert "entry.candles.update(" in source
