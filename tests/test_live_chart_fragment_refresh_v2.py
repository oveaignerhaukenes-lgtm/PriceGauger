from pathlib import Path

from tradingdesk_ui.charts.lightweight.live_update_refresh_v2 import _component_key


def test_live_overlay_uses_payload_revision_for_component_key():
    source = Path("tradingdesk_ui/charts/lightweight/live_update_refresh_v2.py").read_text(encoding="utf-8")
    assert "revision = _revision(candle_payload, markers)" in source
    assert "key=_component_key(str(chart_id), revision)" in source
    assert '"close"' in source


def test_live_overlay_component_key_is_streamlit_bidi_safe():
    key = _component_key(
        "TradingDeskLightweight:US Tech 100 NAS__Saxo",
        "1726470000:25000:25010:24990:25005:4912__CfdOnIndex",
    )
    assert key.startswith("pg-lightweight-live-update-")
    assert "__" not in key


def test_live_overlay_component_key_changes_with_payload_revision():
    first = _component_key("chart", "candle:1")
    second = _component_key("chart", "candle:2")
    assert first != second
    assert _component_key("chart", "candle:1") == first


def test_package_installs_fragment_safe_live_overlay_without_execution_changes():
    source = Path("tradingdesk_ui/charts/lightweight/__init__.py").read_text(encoding="utf-8")
    assert "render_lightweight_live_update_refresh_v2" in source
    assert "_live_update.render_lightweight_live_update_v1 = render_lightweight_live_update_refresh_v2" in source
    assert "persist_intent" not in source
    assert "order_request" not in source


def test_live_overlay_has_browser_heartbeat_not_only_streamlit_run_every():
    source = Path("tradingdesk_ui/charts/lightweight/live_update.py").read_text(encoding="utf-8")
    wrapper = Path("tradingdesk_ui/charts/lightweight/live_update_refresh_v2.py").read_text(encoding="utf-8")
    assert "setTriggerValue('live_tick', Date.now())" in source
    assert "window.setInterval" in source
    assert "window.clearInterval(refreshTimer)" in source
    assert '"refresh_ms": max(0, int(refresh_ms))' in wrapper
    assert "on_live_tick_change=lambda: None" in wrapper


def test_direct_chart_has_independent_one_second_browser_heartbeat():
    source = Path("tradingdesk_ui/charts/lightweight/direct_runtime.py").read_text(encoding="utf-8")
    oslo = Path("tradingdesk_ui/charts/lightweight/direct_runtime_oslo_v2.py").read_text(encoding="utf-8")
    page = Path("pages/0_TradingDesk.py").read_text(encoding="utf-8")
    assert "setTriggerValue('live_tick', Date.now())" in source
    assert "document.visibilityState !== 'hidden'" in source
    assert "on_live_tick_change=lambda: None" in oslo
    assert "refresh_ms=(LIVE_CANDLE_OVERLAY_REFRESH_SECONDS * 1000 if auto_refresh else 0)" in page
