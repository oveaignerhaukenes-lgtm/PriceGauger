from __future__ import annotations

from pathlib import Path


def test_tradingdesk_renders_automanager_in_main_chart_pane_not_right_controls():
    source = Path("pages/0_TradingDesk.py").read_text(encoding="utf-8")
    assert 'CONTROLS_WIDTH_STATE_KEY = "tradingdesk-controls-width-pct"' in source
    assert "def _render_automanager_workspace()" in source
    assert "render_tradingdesk_automanage_panel_v2(context)" in source
    assert "render_tradingdesk_automanage_pnl_chart_v2(context, observations=observations)" in source
    assert "with chart_column:" in source


def test_simple_automanage_panel_is_generic_product_strategy_control_not_order_submitter():
    source = Path("tradingdesk_automanager_simple_v1.py").read_text(encoding="utf-8")
    assert "_position_observations_v2" in source
    assert "AUTOTRADER_STRATEGIES_V2" in source
    assert "enroll_strategy_position_v2" in source
    assert "request_manual_target_v2" in source
    assert 'st.toggle("Manage position"' in source
    assert 'f"BUY @' in source
    assert 'f"SELL @' in source
    assert "session.post" not in source
    assert "_post_once" not in source
    assert "trade/v2/orders" not in source
    assert "4912" not in source


def test_automanage_interactive_controls_remain_streamlit_fragment_scoped():
    source = Path("tradingdesk_automanage_panel_v2.py").read_text(encoding="utf-8")
    assert "@st.fragment" in source
    assert "def _automanager_fragment_v2()" in source
    assert "render_tradingdesk_automanager_simple_v1(context)" in source


def test_pnl_read_model_remains_persisted_and_separate_from_simple_control_plane():
    legacy = Path("tradingdesk_automanage_panel_legacy_v2.py").read_text(encoding="utf-8")
    facade = Path("tradingdesk_automanage_panel_v2.py").read_text(encoding="utf-8")
    assert "load_persisted_strategy_series_v1" in legacy
    assert "load_shadow_benchmark_snapshots_v2" not in legacy
    assert "load_automanager_pnl_comparison_v2" in legacy
    assert "build_automanager_pnl_figure_v2" in legacy
    assert "render_tradingdesk_automanage_pnl_chart_v2" in facade


def test_simple_core_removes_activation_ack_and_manual_takeover_ceremony():
    source = Path("tradingdesk_automanager_simple_v1.py").read_text(encoding="utf-8")
    assert "Jeg vil at PriceGauger skal AutoManage" not in source
    assert '"Aktiver AutoManager"' not in source
    assert "Overta denne posisjonen" not in source
    assert "SHADOW-strategi" not in source
    assert "adopt_user_confirmed_position_v2" in source
    assert "is_position_managed_v1" in source


def test_live_chart_exposes_explicit_clickable_macd_timeframe_without_rearming_execution():
    source = Path("pages/0_TradingDesk.py").read_text(encoding="utf-8")
    assert 'MACD_TIMEFRAME_STATE_KEY = "tradingdesk_macd_timeframe"' in source
    assert 'st.popover(f"MACD · {_timeframe_label(macd_timeframe)}"' in source
    assert '"MACD-timeframe"' in source
    assert "Kun chartvisning" in source
    assert "indicator_timeframes={INDICATOR_MACD:" in source


def test_simple_core_strategy_selector_is_catalog_driven_and_hot_switches_existing_controller():
    source = Path("tradingdesk_automanager_simple_v1.py").read_text(encoding="utf-8")
    assert "AUTOTRADER_STRATEGIES_V2" in source
    assert "switch_live_strategy_v2" in source
    assert "selected_strategy.key != enrollment.strategy_key" in source
    assert "product already has an active LIVE AutoManage controller" not in source


def test_bottom_chart_keeps_actual_live_and_persisted_model_semantics_separate():
    legacy = Path("tradingdesk_automanage_panel_legacy_v2.py").read_text(encoding="utf-8")
    assert "load_automanager_pnl_comparison_v2" in legacy
    assert "build_automanager_pnl_figure_v2" in legacy
    assert "P/L · LIVE og modellene" in legacy
    assert "TradingDesk kjører ikke historisk replay" in legacy


def test_bottom_chart_still_exposes_engine_provenance_and_next_status():
    legacy = Path("tradingdesk_automanage_panel_legacy_v2.py").read_text(encoding="utf-8")
    page_source = Path("pages/0_TradingDesk.py").read_text(encoding="utf-8")
    assert "load_automanager_activity_log_v2" in legacy
    assert "Hendelser og neste status" in legacy
    assert "Status nå:" in legacy
    assert "Neste:" in legacy
    assert "render_tradingdesk_automanage_pnl_chart_v2(context, observations=observations)" in page_source


def test_advanced_execution_gate_remains_available_but_is_not_primary_simple_core():
    simple = Path("tradingdesk_automanager_simple_v1.py").read_text(encoding="utf-8")
    advanced = Path("tradingdesk_autotrade_entry_gate_v2.py").read_text(encoding="utf-8")
    assert "render_tradingdesk_autotrade_entry_gate_v2" not in simple
    assert "approve_open_request_v2" in advanced
    assert "ENTRY_MODE_MANUAL_ONLY" in advanced
    assert 'st.page_link("pages/6_AutoTrader_POC.py"' in simple
