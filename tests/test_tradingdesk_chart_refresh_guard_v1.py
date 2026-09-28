"""Regression guards for TradingDesk's one-second chart refresh contract."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_fast_chart_refresh_preserves_slow_studies():
    page = (ROOT / "pages" / "0_TradingDesk.py").read_text()
    assert 'tradingdesk-chart-extra-series:' in page
    assert 'payload["lines"], payload["histograms"] = cached_extras' in page
    assert 'payload["update_revision"] = datetime.now(timezone.utc).timestamp()' in page


def test_visible_and_hidden_chart_ignore_older_payloads():
    renderer = (ROOT / "tradingdesk_ui" / "charts" / "lightweight" / "simple_live_v2.py").read_text()
    assert renderer.count("incomingRevision < Number(entry.lastRevision || 0)") == 2
    assert renderer.count("entry.lastRevision = incomingRevision") == 2
    assert "lastRevision: Number(payload.update_revision || 0)" in renderer


def test_fast_refresh_does_not_mount_visible_chart():
    renderer = (ROOT / "tradingdesk_ui" / "charts" / "lightweight" / "simple_live_v2.py").read_text()
    assert "if not refresh_only:" in renderer
    assert "_simple_live_refresh_component(" in renderer
