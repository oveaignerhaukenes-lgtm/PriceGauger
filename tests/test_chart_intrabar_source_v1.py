from pathlib import Path

def test_live_chart_does_not_depend_on_closed_canonical_bar_for_intrabar_motion():
    from pathlib import Path
    desk = Path("pages/0_TradingDesk.py").read_text(encoding="utf-8")
    standalone = Path("pages/0_Live_Chart.py").read_text(encoding="utf-8")
    assert "load_live_test_snapshot_v1(" in desk and "load_live_test_snapshot_v1(" in standalone
    assert "def _load_standalone_chart_payload():" in desk
    assert "trade_markers=()," in desk
    assert 'render_lightweight_simple_live_v2(payload, key=chart_key, refresh_only=refresh_only)' in desk
    assert '_refresh_live_chart_data()' in desk

def test_tradingdesk_refresh_clock_is_bound_to_named_fragment():
    page=Path("pages/0_TradingDesk.py").read_text(encoding="utf-8")
    assert '@st.fragment(run_every="1000ms")' in page
    assert "st.fragment(run_every=" in page
