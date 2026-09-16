from pathlib import Path


def test_live_overlay_uses_payload_revision_for_component_key():
    source = Path("tradingdesk_ui/charts/lightweight/live_update_refresh_v2.py").read_text(encoding="utf-8")
    assert "revision = _revision(candle_payload, markers)" in source
    assert 'key=f"pg-lightweight-live-update:{chart_id}:{revision}"' in source
    assert '"close"' in source


def test_package_installs_fragment_safe_live_overlay_without_execution_changes():
    source = Path("tradingdesk_ui/charts/lightweight/__init__.py").read_text(encoding="utf-8")
    assert "render_lightweight_live_update_refresh_v2" in source
    assert "_live_update.render_lightweight_live_update_v1 = render_lightweight_live_update_refresh_v2" in source
    assert "persist_intent" not in source
    assert "order_request" not in source
