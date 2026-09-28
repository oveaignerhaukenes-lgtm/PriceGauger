from pathlib import Path

def test_chart_prefers_canonical_refresh_without_forming_overlay():
    from pathlib import Path
    desk = Path("pages/0_TradingDesk.py").read_text(encoding="utf-8")
    standalone = Path("pages/0_Live_Chart.py").read_text(encoding="utf-8")
    assert "load_live_test_snapshot_v1(" in desk and "load_live_test_snapshot_v1(" in standalone
    assert "def _load_standalone_chart_payload():" in desk
    assert "trade_markers=()," in desk
    assert 'render_lightweight_simple_live_v2(payload, key=chart_key, refresh_only=refresh_only)' in desk
    assert 'lambda: _render_live_chart(refresh_only=True)' in desk

def test_v3_ui_distinguishes_armed_from_managing():
    ui=Path("tradingdesk_automanager_simple_v1.py").read_text(encoding="utf-8")
    assert "NOT MANAGING / ingen worker-heartbeat" in ui
    assert "LIVE MANAGING" in ui

def test_v3_runtime_persists_management_heartbeat():
    runtime=Path("autotrader_v3_live_runtime_v1.py").read_text(encoding="utf-8")
    assert "autotrader_v3_live_runtime_state" in runtime
    assert '"MANAGING"' in runtime
