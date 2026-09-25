from tradingdesk_ui.charts.lightweight.simple_live_v2 import _payload_key


def test_refresh_key_tracks_closed_and_forming_candle_changes():
    payload = {
        "chart_id": "Gold", "signature": "gold|5m",
        "candles": [{"time": 1, "close": 100}],
        "forming_candle": {"time": 2, "close": 101, "updated_at": "a"},
    }
    original = _payload_key("pg-simple-refresh", payload)
    assert original == _payload_key("pg-simple-refresh", dict(payload))
    assert original != _payload_key("pg-simple-refresh", {
        **payload, "forming_candle": {**payload["forming_candle"], "close": 102},
    })
    assert original != _payload_key("pg-simple-refresh", {
        **payload, "candles": [{"time": 1, "close": 102}],
    })


def test_chart_key_does_not_change_with_market_data():
    identity = {"key": "tradingdesk:Gold", "signature": "gold|5m"}
    assert _payload_key("pg-simple-chart", identity) == _payload_key("pg-simple-chart", dict(identity))
    assert _payload_key("pg-simple-chart", identity) != _payload_key(
        "pg-simple-chart", {**identity, "signature": "gold|15m"},
    )


def test_visible_chart_stays_outside_timed_fragments():
    from pathlib import Path

    desk = Path("pages/0_TradingDesk.py").read_text(encoding="utf-8")
    standalone = Path("pages/0_Live_Chart.py").read_text(encoding="utf-8")
    renderer = Path("tradingdesk_ui/charts/lightweight/simple_live_v2.py").read_text(encoding="utf-8")
    assert desk.index("    _render_live_chart()\n") < desk.index("lambda: _render_live_chart(refresh_only=True)")
    assert standalone.index("render_lightweight_simple_live_v2(payload") < standalone.index("@st.fragment(run_every=")
    assert "st_autorefresh" not in standalone
    assert "if not refresh_only:" in renderer
    assert "revision !== entry.closedRevision" in renderer
