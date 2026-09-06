from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from autotrader_trade_markers_v1 import AutoTraderTradeMarkerV1
from trading_desk import ChartBar
from trading_desk_chart import OVERLAY_NORMALIZED
from trading_desk_indicators import IndicatorPoint, TechnicalIndicators
from tradingdesk_ui.charts.lightweight.contract import build_lightweight_live_payload_v1


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


def test_lightweight_contract_is_json_safe_and_preserves_price_series() -> None:
    bars = _bars()
    technical = TechnicalIndicators(
        bollinger_middle=_points(bars, 0.0),
        bollinger_upper=_points(bars, 20.0),
        bollinger_lower=_points(bars, -20.0),
        vwap=_points(bars, -2.0),
        macd=tuple(IndicatorPoint(bar_time=bar.bar_time, value=index * 0.5) for index, bar in enumerate(bars)),
        macd_signal=tuple(IndicatorPoint(bar_time=bar.bar_time, value=index * 0.4) for index, bar in enumerate(bars)),
        macd_histogram=tuple(IndicatorPoint(bar_time=bar.bar_time, value=index * 0.1) for index, bar in enumerate(bars)),
        rsi=tuple(IndicatorPoint(bar_time=bar.bar_time, value=45.0 + index) for index, bar in enumerate(bars)),
    )
    marker = AutoTraderTradeMarkerV1(
        executed_at=datetime(2026, 9, 4, 20, 47, tzinfo=timezone.utc),
        execution_price=29491.0,
        direction="LONG",
        amount=1.0,
        strategy_key="macd-5m-shadow-v1",
        net_position_id="np-1",
        active=True,
        source="autotrader",
    )

    payload = build_lightweight_live_payload_v1(
        market="US Tech 100 NAS",
        timeframe="5m",
        primary=bars,
        overlays={},
        overlay_mode=OVERLAY_NORMALIZED,
        indicators=technical,
        indicator_names=("Bollinger", "MACD", "RSI", "VWAP"),
        indicator_timeframes={"MACD": "5m"},
        chart_height=780,
        price_panel_share=0.5,
        trade_markers=(marker,),
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


def test_lightweight_renderer_uses_native_chart_navigation_not_plotly_relayout() -> None:
    source = (ROOT / "tradingdesk_ui" / "charts" / "lightweight" / "renderer.py").read_text(encoding="utf-8")
    assert "lightweight-charts@5.2.1" in source
    assert "pinch: true" in source
    assert "pressedMouseMove: true" in source
    assert "axisPressedMouseMove" in source
    assert "axisDoubleClickReset" in source
    assert "kineticScroll" in source
    assert "attributionLogo: true" in source
    assert "Plotly.relayout" not in source


def test_transitional_bridge_covers_live_plotly_with_native_lightweight_canvas() -> None:
    source = (ROOT / "tradingdesk_ui" / "charts" / "lightweight" / "bridge.py").read_text(encoding="utf-8")
    assert "key.startsWith('TradingDesk:')" in source
    assert "pg-lightweight-bridge-root" in source
    assert "zIndex: '50'" in source
    assert "pinch: true" in source
    assert "axisPressedMouseMove" in source
    assert "createSeriesMarkers" in source
    assert "atPriceMiddle" in source
    assert "window.__pricegaugerLiveCandleOverlays" in source


def test_lightweight_bridge_mounts_with_live_chart_and_legacy_gesture_layer_is_not_mounted() -> None:
    page = (ROOT / "pages" / "0_TradingDesk.py").read_text(encoding="utf-8")
    controls = page.split("def _render_live_chart_controls() -> None:", 1)[1].split(
        "def _live_chart_uirevision()", 1
    )[0]
    assert "tradingdesk_ui.charts.lightweight.bridge" in page
    assert "render_lightweight_plotly_bridge_v1()" in controls
    assert "render_trading_desk_legend_hover_v1" not in page


def test_lightweight_presentation_cleanup_hides_indicator_value_chips_until_interaction() -> None:
    source = (ROOT / "tradingdesk_ui" / "charts" / "lightweight" / "presentation_cleanup.py").read_text(
        encoding="utf-8"
    )
    page = (ROOT / "pages" / "0_TradingDesk.py").read_text(encoding="utf-8")
    assert "entry.candles?.applyOptions?.({ title: '', lastValueVisible: true })" in source
    assert "lastValueVisible: false" in source
    assert "legend.style.opacity = '0'" in source
    assert "pointermove" in source
    assert "render_lightweight_presentation_cleanup_v1()" in page


def test_lightweight_timeframe_toolbar_exposes_intraday_workline() -> None:
    source = (ROOT / "tradingdesk_ui" / "charts" / "lightweight" / "toolbar.py").read_text(encoding="utf-8")
    assert '("1m", "2m", "5m", "10m", "15m", "30m")' in source
    assert "st.columns(len(LIGHTWEIGHT_TIMEFRAMES_V1)" in source
    assert 'type="primary" if current == value else "secondary"' in source


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
