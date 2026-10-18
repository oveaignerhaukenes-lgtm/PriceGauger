"""Read-only forming-delta contract and TradingDesk refresh boundaries."""

from pathlib import Path

from tradingdesk_ui.charts.lightweight.direct_contract import (
    build_lightweight_forming_delta_v1,
)


def test_forming_delta_does_not_overwrite_full_candles_or_markers():
    baseline = {
        "chart_id": "TradingDeskLightweight:Gold",
        "signature": "gold|5m|studies",
        "candles": [{"time": 1, "close": 7}],
        "markers": [{"time": 1, "text": "LONG"}],
        "lines": [{"role": "macd", "data": [1, 2]}],
        "update_revision": 4,
    }
    delta = build_lightweight_forming_delta_v1(
        baseline=baseline, timeframe="5m", forming_candle=None,
    )
    assert delta == {
        "chart_id": baseline["chart_id"],
        "signature": baseline["signature"],
        "forming_candle": None,
        "delta_only": True,
        "update_revision": 4,
    }


def test_incremental_refresh_only_applies_to_readonly_tradingdesk():
    desk = Path("pages/0_TradingDesk.py").read_text(encoding="utf-8")
    js = Path("tradingdesk_ui/charts/lightweight/simple_live_v2.py").read_text(
        encoding="utf-8"
    )
    history = Path(
        "tradingdesk_ui/charts/lightweight/live_chart_history_cache_v1.py"
    ).read_text(encoding="utf-8")
    assert "def _load_standalone_chart_payload(*, refresh_only: bool = False)" in desk
    assert "build_lightweight_forming_delta_v1(" in desk
    assert "technical, selected_indicators = _load_chart_indicators_v1(closed)" in desk
    assert "revision == old_revision" in desk
    assert "from time import monotonic" in desk
    assert 'const deltaOnly = payload.delta_only === true;' in js
    assert "if (!deltaOnly) {" in js
    assert "entry.candles.setData(candles)" in js
    assert 'entry.markers?.setMarkers?.(' in js
    assert "from saxo_chart_live import" in history
    assert "run_live_close" not in history
    assert "submit_order" not in history
