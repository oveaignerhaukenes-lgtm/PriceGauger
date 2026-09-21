from pathlib import Path

from tradingdesk_ui.charts.lightweight.base_update_v1 import _base_revision, _component_key


def test_base_revision_changes_when_closed_candle_or_indicator_changes() -> None:
    base = {
        "chart_id": "TradingDeskLightweight:US Tech",
        "signature": "sig",
        "candles": [{"time": 1, "open": 10, "high": 11, "low": 9, "close": 10}],
        "volume": [],
        "lines": [{"role": "macd", "data": [{"time": 1, "value": 0.1}]}],
        "histograms": [],
    }
    changed_candle = {**base, "candles": [{**base["candles"][0], "close": 10.5}]}
    changed_macd = {
        **base,
        "lines": [{"role": "macd", "data": [{"time": 1, "value": 0.2}]}],
    }
    assert _base_revision(base) != _base_revision(changed_candle)
    assert _base_revision(base) != _base_revision(changed_macd)


def test_base_update_component_key_is_bidi_safe() -> None:
    key = _component_key("US Tech__4912", "bar__revision")
    assert key.startswith("pg-lightweight-base-update-")
    assert "__" not in key


def test_legacy_base_updater_is_not_mounted_cross_iframe_and_has_no_execution_authority() -> None:
    source = Path("tradingdesk_ui/charts/lightweight/base_update_v1.py").read_text(encoding="utf-8")
    page = Path("pages/0_TradingDesk.py").read_text(encoding="utf-8")

    assert "registry?.get?.(chartId)" in source
    assert "entry.candles.setData(candleData)" in source
    assert "entry.series?.get?.(String(item.role))?.setData" in source
    assert "entry.formingCandles instanceof Map" in source
    assert "render_lightweight_base_update_v1(payload)" not in page

    lowered = source.lower()
    for forbidden in (
        "trade/v2/orders",
        "session.post(",
        "requests.post(",
        "persist_intent",
        "execution_request",
    ):
        assert forbidden not in lowered
