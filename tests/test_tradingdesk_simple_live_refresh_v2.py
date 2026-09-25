from tradingdesk_ui.charts.lightweight.simple_live_v2 import _payload_key


def test_initial_chart_and_fragment_do_not_mount_duplicate_refresh_keys(monkeypatch):
    import tradingdesk_ui.charts.lightweight.simple_live_v2 as renderer

    visible, updates = [], []
    monkeypatch.setattr(renderer, "_simple_live_component", lambda **kwargs: visible.append(kwargs))
    monkeypatch.setattr(renderer, "_simple_live_refresh_component", lambda **kwargs: updates.append(kwargs))
    payload = {"chart_id": "market", "signature": "5m", "height": 450, "candles": []}

    renderer.render_lightweight_simple_live_v2(payload, key="desk")
    assert len(visible) == 1
    assert updates == []

    renderer.render_lightweight_simple_live_v2(payload, key="desk", refresh_only=True)
    renderer.render_lightweight_simple_live_v2(payload, key="other", refresh_only=True)
    assert len(visible) == 1
    assert len(updates) == 2
    assert updates[0]["key"] != updates[1]["key"]


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


def test_tradingdesk_refresh_uses_the_live_test_snapshot_before_indicator_work():
    from pathlib import Path

    desk = Path("pages/0_TradingDesk.py").read_text(encoding="utf-8")
    test_chart = Path("pages/0_Live_Chart.py").read_text(encoding="utf-8")
    assert "load_live_test_snapshot_v1(" in desk
    assert "load_live_test_snapshot_v1(" in test_chart
    refresh = desk.split("def _render_live_chart(*, refresh_only: bool = False) -> None:", 1)[1]
    assert refresh.index("if refresh_only:") < refresh.index("calculate_indicators(indicator_source)")
    assert 'payload["signature"] = st.session_state.get(' in refresh
    assert 'rollover_events=(),' in refresh


def test_trade_and_rollover_markers_are_sorted_and_keep_their_shapes():
    from pathlib import Path

    contract = Path("tradingdesk_ui/charts/lightweight/direct_contract.py").read_text(encoding="utf-8")
    renderer = Path("tradingdesk_ui/charts/lightweight/simple_live_v2.py").read_text(encoding="utf-8")
    assert 'payload["markers"].sort(key=lambda marker: int(marker["time"]))' in contract
    assert renderer.count("if (!['LONG', 'SHORT', 'FLAT'].includes(direction)) return marker;") == 2
