from pathlib import Path


def test_three_trader_lab_uses_tv_chart_v1():
    root = Path(__file__).resolve().parents[1]
    lab = (root / "tradingdesk_three_trader_lab_v1.py").read_text(encoding="utf-8")
    chart = (root / "tradingdesk_ui/charts/lightweight/three_trader_tv_v1.py").read_text(encoding="utf-8")
    assert "render_three_trader_tv_v1" in lab
    assert "st.plotly_chart" not in lab
    assert "handleScroll" in chart
    assert "pinch: true" in chart
    assert "pressedMouseMove: true" in chart
    assert "localStorage" in chart
    assert "pointerdown" in chart
    assert "saved.height" in chart
