from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_chart_buy_sell_shortcuts_use_manual_target_lifecycle() -> None:
    source = (ROOT / "tradingdesk_chart_trade_controls_v1.py").read_text(encoding="utf-8")
    assert "setTriggerValue('trade_action'" in source
    assert "request_manual_target_v2" in source
    assert "_ensure_execution_ready_v1" in source
    assert "configured_client" in source
    assert "_post(" not in source
    assert "requests.post" not in source


def test_chart_controls_render_inside_existing_lightweight_chart_root() -> None:
    source = (ROOT / "tradingdesk_chart_trade_controls_v1.py").read_text(encoding="utf-8")
    assert "window.__pricegaugerLightweightCharts" in source
    assert "entry?.root" in source
    assert "position: 'absolute'" in source
    assert "left: '6px'" in source
    assert "top: '6px'" in source
    assert "BUY" in source and "SELL" in source


def test_scheduled_refresh_reuses_same_signature_chart_and_defers_heavy_update() -> None:
    source = (ROOT / "tradingdesk_chart_runtime_continuity_v1.py").read_text(encoding="utf-8")
    assert "sameSignature && entry.parent !== parentElement" in source
    assert "parentElement.appendChild(entry.root)" in source
    assert "requestIdleCallback" in source
    assert "preferredHeight()" in source
    assert "applySavedPaneGeometry(chart)" in source


def test_base_and_live_trade_markers_share_blue_gold_palette() -> None:
    source = (ROOT / "tradingdesk_chart_runtime_continuity_v1.py").read_text(encoding="utf-8")
    live = (ROOT / "tradingdesk_ui" / "charts" / "lightweight" / "live_update.py").read_text(encoding="utf-8")
    assert '#0ea5e9' in source and '#f59e0b' in source
    assert '#0ea5e9' in live and '#f59e0b' in live


def test_automanager_facade_installs_chart_continuity_before_runtime_use() -> None:
    source = (ROOT / "tradingdesk_automanage_panel_v2.py").read_text(encoding="utf-8")
    assert "install_chart_runtime_continuity_v1()" in source
    assert "render_tradingdesk_chart_trade_controls_v1(context, observations=observations)" in source
