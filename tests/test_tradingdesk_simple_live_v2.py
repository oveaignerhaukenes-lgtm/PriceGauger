from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_tradingdesk_uses_simple_live_v2_renderer() -> None:
    page = (ROOT / "pages" / "0_TradingDesk.py").read_text(encoding="utf-8")
    assert "from tradingdesk_ui.charts.lightweight.simple_live_v2 import render_lightweight_simple_live_v2" in page
    assert "render_lightweight_simple_live_v2(" in page
    assert "render_lightweight_direct_live_v1(" not in page


def test_simple_renderer_keeps_primary_model_evaluation_surfaces() -> None:
    source = (ROOT / "tradingdesk_ui" / "charts" / "lightweight" / "simple_live_v2.py").read_text(
        encoding="utf-8"
    )
    assert "LWC.CandlestickSeries" in source
    assert "payload.markers" in source
    assert "LWC.createSeriesMarkers" in source
    assert "payload.lines" in source
    assert "payload.histograms" in source
    assert "payload.forming_candle" in source


def test_simple_renderer_has_no_source_rewrite_or_execution_authority() -> None:
    source = (ROOT / "tradingdesk_ui" / "charts" / "lightweight" / "simple_live_v2.py").read_text(
        encoding="utf-8"
    )
    forbidden = (
        "_replace_required",
        "_DIRECT_LIVE_JS",
        "tradingdesk_chart_runtime_continuity",
        "saxo_order",
        "submit_order",
        "place_order",
        "AutoManager",
    )
    for token in forbidden:
        assert token not in source
