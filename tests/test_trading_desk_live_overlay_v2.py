from __future__ import annotations

from pathlib import Path

from saxo_chart_live import FormingCandle1m
from trading_desk_live_overlay_v2 import (
    forming_candle_payload_v2,
    live_chart_overlay_key_v2,
    parse_live_chart_view_v2,
)


def _candle() -> FormingCandle1m:
    return FormingCandle1m(
        market="US Tech 100",
        bar_time="2026-08-31T12:30:00+00:00",
        open=23500.0,
        high=23510.0,
        low=23495.0,
        close=23508.0,
        volume=12.0,
        provider="Saxo chart stream",
        uic=1907570,
        asset_type="CfdOnIndex",
        symbol="USNAS100.I",
        delayed_by_minutes=0.0,
        source_event_at="2026-08-31T12:30:01+00:00",
        updated_at="2026-08-31T12:30:01+00:00",
    )


def test_forming_candle_payload_is_browser_only_price_data_in_oslo_time() -> None:
    payload = forming_candle_payload_v2(_candle())

    assert payload == {
        "bar_time": "2026-08-31T14:30:00",
        "open": 23500.0,
        "high": 23510.0,
        "low": 23495.0,
        "close": 23508.0,
    }
    assert "volume" not in payload
    assert "uic" not in payload
    assert forming_candle_payload_v2(_candle(), timeframe_minutes=30)["bar_time"] == "2026-08-31T14:30:00"


def test_saved_chart_view_compatibility_parser_still_validates_old_payloads() -> None:
    view = parse_live_chart_view_v2(
        {
            "view": {
                "x_range": ["2026-08-31 10:00", "2026-08-31 12:00"],
                "y_range": [23400, 23600],
            }
        }
    )

    assert view is not None
    assert view.x_range == ("2026-08-31 10:00", "2026-08-31 12:00")
    assert view.y_range == (23400.0, 23600.0)
    assert parse_live_chart_view_v2({"view": {"x_range": ["a"], "y_range": [1, 2]}}) is None
    assert parse_live_chart_view_v2({"view": {"x_range": ["a", "b"], "y_range": [1, float("nan")]}}) is None


def test_overlay_component_draws_without_intercepting_pointer_navigation() -> None:
    source = Path("trading_desk_live_overlay_v2.py").read_text(encoding="utf-8")

    assert "document.createElement('canvas')" in source
    assert "pointerEvents: 'none'" in source
    assert "plotly_relayout" in source
    assert "plotly_afterplot" in source
    assert "plotly_doubleclick" in source
    assert "entry.view = view" in source
    assert "applyStoredView" in source
    assert "window.__pricegaugerLiveCandleOverlays" in source
    assert "setStateValue('view', view)" not in source
    assert live_chart_overlay_key_v2("revision") == "pg-live-candle-overlay:revision"


def test_browser_local_view_restore_is_guarded_and_double_click_clears_it() -> None:
    source = Path("trading_desk_live_overlay_v2.py").read_text(encoding="utf-8")

    assert "entry.restoringView" in source
    assert "viewsEqual(current, entry.view)" in source
    assert "'xaxis.autorange': false" in source
    assert "'yaxis.autorange': false" in source
    assert "entry.view = null" in source
    assert "entry.resettingView = true" in source
