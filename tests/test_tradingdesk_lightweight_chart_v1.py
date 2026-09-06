from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from autotrader_trade_markers_v1 import AutoTraderTradeMarkerV1
from trading_desk import ChartBar
from trading_desk_chart import OVERLAY_NORMALIZED
from trading_desk_indicators import IndicatorPoint, TechnicalIndicators
from tradingdesk_ui.charts.lightweight.contract import build_lightweight_live_payload_v1
from tradingdesk_ui.charts.lightweight.direct_contract import build_lightweight_direct_live_payload_v1


ROOT = Path(__file__).resolve().parents[1]


def _bars(count: int = 4) -> tuple[ChartBar, ...]:
    start = datetime(2026, 9, 4, 20, 40, tzinfo=timezone.utc)
    result = []
    for index in range(count):
        price = 29480.0 + index * 4.0
        result.append(
            ChartBar(
                market="US Tech 100 NAS",
                bar_time=(start + timedelta(minutes=index * 5)).isoformat(),
                open=price,
                high=price + 7.0,
                low=price - 5.0,
                close=price + 2.0,
                volume=100.0 + index,
            )
        )
    return tuple(result)


def _points(bars: tuple[ChartBar, ...], offset: float) -> tuple[IndicatorPoint, ...]:
    return tuple(IndicatorPoint(bar_time=bar.bar_time, value=bar.close + offset) for bar in bars)


def _technical(bars: tuple[ChartBar, ...]) -> TechnicalIndicators:
    return TechnicalIndicators(
        bollinger_middle=_points(bars, 0.0),
        bollinger_upper=_points(bars, 20.0),
        bollinger_lower=_points(bars, -20.0),
        vwap=_points(bars, -2.0),
        macd=tuple(IndicatorPoint(bar_time=bar.bar_time, value=index * 0.5) for index, bar in enumerate(bars)),
        macd_signal=tuple(IndicatorPoint(bar_time=bar.bar_time, value=index * 0.4) for index, bar in enumerate(bars)),
        macd_histogram=tuple(IndicatorPoint(bar_time=bar.bar_time, value=index * 0.1) for index, bar in enumerate(bars)),
        rsi=tuple(IndicatorPoint(bar_time=bar.bar_time, value=45.0 + index) for index, bar in enumerate(bars)),
    )


def _marker() -> AutoTraderTradeMarkerV1:
    return AutoTraderTradeMarkerV1(
        executed_at=datetime(2026, 9, 4, 20, 47, tzinfo=timezone.utc),
        execution_price=29491.0,
        direction="LONG",
        amount=1.0,
        strategy_key="macd-5m-shadow-v1",
        net_position_id="np-1",
        active=True,
        source="autotrader",
    )


def test_lightweight_contract_is_json_safe_and_preserves_price_series() -> None:
    bars = _bars()
    payload = build_lightweight_live_payload_v1(
        market="US Tech 100 NAS",
        timeframe="5m",
        primary=bars,
        overlays={},
        overlay_mode=OVERLAY_NORMALIZED,
        indicators=_technical(bars),
        indicator_names=("Bollinger", "MACD", "RSI", "VWAP"),
        indicator_timeframes={"MACD": "5m"},
        chart_height=780,
        price_panel_share=0.5,
        trade_markers=(_marker(),),
    )

    assert payload["version"] == 1
    assert payload["candles"][0]["open"] == bars[0].open
    assert payload["candles"][-1]["close"] == bars[-1].close
    assert payload["pane_order"] == ["price", "macd", "rsi"]
    roles = {item["role"] for item in payload["lines"]}
    assert {"bollinger_upper", "bollinger_middle", "bollinger_lower", "vwap", "macd", "macd_signal", "rsi"} <= roles
    assert payload["histograms"][0]["role"] == "macd_histogram"
    assert payload["markers"][0]["position"] == "atPriceMiddle"
    assert payload["markers"][0]["price"] == 29491.0
    assert payload["markers"][0]["shape"] == "arrowUp"
    assert isinstance(payload["candles"][0]["time"], int)


def test_direct_contract_keeps_stable_contract_and_adds_structural_slot() -> None:
    bars = _bars()
    payload = build_lightweight_direct_live_payload_v1(
        market="US Tech 100 NAS",
        timeframe="5m",
        primary=bars,
        overlays={},
        overlay_mode=OVERLAY_NORMALIZED,
        indicators=_technical(bars),
        indicator_names=("Bollinger", "MACD", "RSI", "VWAP", "Swing high/low"),
        indicator_timeframes={"MACD": "5m"},
        chart_height=780,
        price_panel_share=0.5,
        trade_markers=(_marker(),),
    )

    assert payload["version"] == 1
    assert "swing_bands" in payload
    assert "direct-v1" in payload["signature"]
    assert payload["markers"][0]["price"] == 29491.0


def test_direct_lightweight_runtime_owns_native_navigation_without_plotly() -> None:
    source = (ROOT / "tradingdesk_ui" / "charts" / "lightweight" / "direct_runtime.py").read_text(
        encoding="utf-8"
    )
    assert "lightweight-charts@5.2.1" in source
    assert "pinch: true" in source
    assert "pressedMouseMove: true" in source
    assert "axisPressedMouseMove" in source
    assert "axisDoubleClickReset" in source
    assert "kineticScroll" in source
    assert "attributionLogo: true" in source
    assert "window.__pricegaugerLightweightCharts" in source
    assert "baseCandles" in source
    assert "formingCandles" in source
    assert "window.Plotly" not in source
    assert "Plotly.relayout" not in source


def test_direct_runtime_declutters_series_but_keeps_current_candle_price() -> None:
    source = (ROOT / "tradingdesk_ui" / "charts" / "lightweight" / "direct_runtime.py").read_text(
        encoding="utf-8"
    )
    assert "title: '', upColor" in source
    assert "priceLineVisible: true, lastValueVisible: true" in source
    assert "priceLineVisible: false, lastValueVisible: false" in source
    assert "inspector.style.opacity = '0'" in source
    assert "subscribeCrosshairMove" in source


def test_native_live_update_updates_forming_candle_and_trade_markers_in_same_registry() -> None:
    source = (ROOT / "tradingdesk_ui" / "charts" / "lightweight" / "live_update.py").read_text(
        encoding="utf-8"
    )
    assert "window.__pricegaugerLightweightCharts" in source
    assert "entry.candles.update(merged)" in source
    assert "entry.baseCandles" in source
    assert "entry.formingCandles" in source
    assert "entry.markers?.setMarkers?." in source
    assert "window.Plotly" not in source
    assert "Plotly.relayout" not in source


def test_touch_price_axis_drag_uses_native_visible_range_api_for_every_pane() -> None:
    source = (ROOT / "tradingdesk_ui" / "charts" / "lightweight" / "live_update.py").read_text(
        encoding="utf-8"
    )
    assert "ensureTouchPriceAxisDrag(entry)" in source
    assert "pg-lightweight-touch-price-axis" in source
    assert "scaleSeriesForPanes(entry)" in source
    assert "paneIndexAtY(entry, event.clientY)" in source
    assert "['macd', 'macd_signal', 'macd_histogram']" in source
    assert "['rsi']" in source
    assert "['stochastic_k', 'stochastic_d']" in source
    assert "['atr']" in source
    assert "getVisibleRange?.()" in source
    assert "setAutoScale(false)" in source
    assert "setVisibleRange({ from: center - nextHalf, to: center + nextHalf })" in source
    assert "width: '82px'" in source
    assert "touchAction: 'none'" in source
    assert "new MouseEvent" not in source
    assert "dispatchMouse" not in source


def test_touch_time_axis_drag_scales_x_axis_and_double_tap_fits_content() -> None:
    source = (ROOT / "tradingdesk_ui" / "charts" / "lightweight" / "live_update.py").read_text(
        encoding="utf-8"
    )
    assert "ensureTouchTimeAxisScale(entry)" in source
    assert "pg-lightweight-touch-time-axis" in source
    assert "getVisibleLogicalRange?.()" in source
    assert "setVisibleLogicalRange({ from: center - nextHalf, to: center + nextHalf })" in source
    assert "drag.timeScale.fitContent()" in source
    assert "cursor: 'ew-resize'" in source
    assert "height: '34px'" in source


def test_trade_markers_use_non_candle_colors_for_long_and_short() -> None:
    source = (ROOT / "tradingdesk_ui" / "charts" / "lightweight" / "live_update.py").read_text(
        encoding="utf-8"
    )
    assert "direction === 'LONG' ? '#0ea5e9' : '#f59e0b'" in source
    assert "direction === 'LONG' ? '#16a34a' : '#dc2626'" not in source


def test_bottom_handle_resizes_whole_chart_and_preserves_pane_ratios() -> None:
    source = (ROOT / "tradingdesk_ui" / "charts" / "lightweight" / "live_update.py").read_text(
        encoding="utf-8"
    )
    assert "ensureChartHeightResize(entry)" in source
    assert "pg-lightweight-chart-height-resize" in source
    assert "entry.parent.style.height" in source
    assert "applyPaneRatios(entry, drag?.ratios || [])" in source
    assert "paneRatios(entry)" in source
    assert "pg:tradingdesk:lightweight-geometry:v1:" in source
    assert "window.localStorage" in source
    assert "pane_ratios" in source
    assert "bottom: '34px'" in source
    assert "ensureBottomPaneResize" not in source
    assert "drag.lastPane.setHeight" not in source


def test_tradingdesk_mounts_direct_renderer_and_not_transitional_bridge() -> None:
    page = (ROOT / "pages" / "0_TradingDesk.py").read_text(encoding="utf-8")
    live_chart = page.split("def _render_live_chart() -> None:", 1)[1].split(
        "def _render_lightweight_live_update()", 1
    )[0]
    assert "build_lightweight_direct_live_payload_v1(" in live_chart
    assert "render_lightweight_direct_live_v1(" in live_chart
    assert "st.plotly_chart(" not in live_chart
    assert "render_lightweight_plotly_bridge_v1" not in page
    assert "render_lightweight_presentation_cleanup_v1" not in page
    assert "render_trading_desk_legend_hover_v1" not in page


def test_lightweight_timeframe_toolbar_exposes_intraday_workline() -> None:
    source = (ROOT / "tradingdesk_ui" / "charts" / "lightweight" / "toolbar.py").read_text(encoding="utf-8")
    assert '("1m", "2m", "5m", "10m", "15m", "30m")' in source
    assert "st.segmented_control(" in source
    assert 'selection_mode="single"' in source
    assert "required=True" in source
    assert "wrap=False" in source
    assert 'label_visibility="collapsed"' in source
    assert "st.columns(" not in source


def test_lightweight_boundary_contains_no_execution_authority() -> None:
    root = ROOT / "tradingdesk_ui" / "charts" / "lightweight"
    source = "\n".join(path.read_text(encoding="utf-8") for path in root.rglob("*.py"))
    forbidden = (
        "place_order",
        "submit_order",
        "autotrader_live_open",
        "autotrader_live_close",
        "SaxoOrder",
        "PositionGuardian",
    )
    for token in forbidden:
        assert token not in source
