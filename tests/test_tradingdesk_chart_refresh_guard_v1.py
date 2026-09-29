"""Regression guards for TradingDesk's one-second chart refresh contract."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_fast_chart_refresh_preserves_slow_studies():
    from pathlib import Path
    desk = Path("pages/0_TradingDesk.py").read_text(encoding="utf-8")
    standalone = Path("pages/0_Live_Chart.py").read_text(encoding="utf-8")
    assert "load_live_test_snapshot_v1(" in desk and "load_live_test_snapshot_v1(" in standalone
    assert "def _load_standalone_chart_payload():" in desk
    assert "trade_markers=_load_trade_markers()," in desk
    assert 'render_lightweight_simple_live_v2(payload, key=chart_key, refresh_only=refresh_only)' in desk
    assert '_refresh_live_chart_data()' in desk

def test_visible_and_hidden_chart_ignore_older_payloads():
    renderer = (ROOT / "tradingdesk_ui" / "charts" / "lightweight" / "simple_live_v2.py").read_text()
    assert renderer.count("incomingRevision < Number(entry.lastRevision || 0)") == 2
    assert renderer.count("entry.lastRevision = incomingRevision") == 2
    assert "lastRevision: Number(payload.update_revision || 0)" in renderer


def test_fast_refresh_does_not_mount_visible_chart():
    renderer = (ROOT / "tradingdesk_ui" / "charts" / "lightweight" / "simple_live_v2.py").read_text()
    assert "if not refresh_only:" in renderer
    assert "_simple_live_refresh_component(" in renderer
