from __future__ import annotations

from pathlib import Path


def test_interaction_capture_v2_routes_gestures_before_plotly_and_hides_stale_overlay() -> None:
    source = Path("tradingdesk_ui/charts/interaction_capture_v2.py").read_text(encoding="utf-8")
    assert "window.addEventListener('wheel'" in source
    assert "capture: true" in source
    assert "priceAxis(graph)" in source
    assert "axisAt(graph" in source
    assert "zoomX(graph" in source
    assert "panX(graph" in source
    assert "scaleY(graph" in source
    assert "plotly_relayouting" in source
    assert "canvas[id^=\"pg-live-candle-\"]" in source
    assert "canvas.style.opacity = '0'" in source
    assert "canvas.style.opacity = '1'" in source


def test_interaction_capture_v2_is_retained_as_rollback_but_not_mounted_with_lightweight_live() -> None:
    source = Path("tradingdesk_automanage_panel_v2.py").read_text(encoding="utf-8")
    assert "tradingdesk_ui.charts.interaction_capture_v2" not in source
    assert "render_tradingdesk_interaction_capture_v2()" not in source
    assert "render_lightweight_plotly_bridge_v1()" in source


def test_interaction_capture_v2_has_no_execution_authority() -> None:
    source = Path("tradingdesk_ui/charts/interaction_capture_v2.py").read_text(encoding="utf-8")
    forbidden = (
        "SaxoOrder",
        "place_order",
        "submit_order",
        "autotrader_live_open",
        "autotrader_live_close",
        "ProductAdmission",
        "PositionGuardian",
    )
    for token in forbidden:
        assert token not in source
