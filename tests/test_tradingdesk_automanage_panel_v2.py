from __future__ import annotations

from pathlib import Path


def test_tradingdesk_renders_automanager_in_main_chart_pane_not_right_controls():
    source = Path("pages/0_TradingDesk.py").read_text(encoding="utf-8")
    assert "chart_column, controls_column = st.columns([4.8, 1.45]" in source
    assert "def _render_automanager_workspace()" in source
    assert "render_tradingdesk_automanage_panel_v2(context)" in source
    assert "render_tradingdesk_automanage_pnl_chart_v2(context)" in source
    assert "with chart_column:" in source
    assert "_render_automanager_workspace()" in source
    assert 'with st.expander(f"AutoManage · {market}"' not in source
    assert 'with st.expander(f"Handel · {market}"' not in source


def test_automanage_panel_is_generic_product_strategy_enrollment_not_order_submitter():
    source = Path("tradingdesk_automanage_panel_v2.py").read_text(encoding="utf-8")
    assert "_position_observations_v2" in source
    assert "resolve_saxo_automanage_product_v2" in source
    assert "int(product.market_id) == int(context.market_id)" in source
    assert "AUTOTRADER_STRATEGIES_V2" in source
    assert "enroll_strategy_position_v2" in source
    assert "EXECUTION_MODE_LIVE" in source
    assert "EXECUTION_MODE_SHADOW" in source
    assert "Kjør én shadow-strategi for direkte sammenligning" in source
    assert "SHADOW-strategi" in source
    assert "_default_shadow_index" in source
    assert '"long-short" in item.key' in source
    assert "Startkapital" in source
    assert "Pilotkapital" in source
    assert "Realisert" in source
    assert "ENTRY_MODE_LABELS" in source
    assert "render_tradingdesk_autotrade_entry_gate_v2" in source
    assert "Standard er Manage-only" in source
    assert "session.post" not in source
    assert "_post_once" not in source
    assert "CREATE TABLE" not in source
    assert "4912" not in source


def test_automanage_panel_exposes_same_basis_live_shadow_scorecards_even_when_flat():
    source = Path("tradingdesk_automanage_panel_v2.py").read_text(encoding="utf-8")
    assert "load_shadow_benchmark_snapshots_v2" in source
    assert "load_active_strategy_enrollments_v2" in source
    assert "LIVE / SHADOW · samme startgrunnlag" in source
    assert 'st.metric("Paper P/L", f"{item.return_pct:+.2f}%")' in source
    assert "samme observerte startposisjon" in source
    assert "same exact canonical 30m-prisbane" not in source
    assert "samme exact canonical 30m-prisbane" in source
    assert "faktisk Saxo-P/L føres separat i LIVE-ledgeren" in source
    assert "strategitest over forblir synlig" in source


def test_automanage_enrollment_requires_explicit_user_acknowledgement():
    source = Path("tradingdesk_automanage_panel_v2.py").read_text(encoding="utf-8")
    assert "Jeg vil at PriceGauger skal AutoManage denne eksakte LIVE-posisjonen med valgt strategi." in source
    assert "disabled=not acknowledge" in source
    assert '"Aktiver AutoManager"' in source
    assert '"Stopp denne piloten"' in source


def test_changed_manual_basis_requires_explicit_close_authority_adoption():
    source = Path("tradingdesk_automanage_panel_v2.py").read_text(encoding="utf-8")
    assert "is_position_managed_v1(observation)" in source
    assert "adopt_user_confirmed_position_v2" in source
    assert "CLOSE-authority" in source
    assert "fail-closed" in source
    assert "Overta denne posisjonen" in source
    assert "Ingen ordre ble sendt" in source


def test_live_chart_exposes_explicit_clickable_macd_timeframe_without_rearming_execution():
    source = Path("pages/0_TradingDesk.py").read_text(encoding="utf-8")
    assert 'MACD_TIMEFRAME_STATE_KEY = "tradingdesk_macd_timeframe"' in source
    assert 'st.session_state[MACD_TIMEFRAME_STATE_KEY] = "30m"' in source
    assert 'st.popover(f"MACD · {_timeframe_label(macd_timeframe)}"' in source
    assert '"MACD-timeframe"' in source
    assert "Kun chartvisning" in source
    assert "indicator_timeframes={INDICATOR_MACD:" in source


def test_automanage_bottom_chart_keeps_actual_live_and_paper_semantics_separate():
    source = Path("tradingdesk_automanage_panel_v2.py").read_text(encoding="utf-8")
    assert "load_automanager_pnl_comparison_v2" in source
    assert "build_automanager_pnl_figure_v2" in source
    assert "P/L · LIVE og modellene" in source
    assert "bare faktisk, avstemt og realisert netto Saxo-P/L" in source
    assert "long/flat, short/flat og MACD Switch" in source


def test_automanage_bottom_chart_exposes_engine_provenance_and_next_status():
    source = Path("tradingdesk_automanage_panel_v2.py").read_text(encoding="utf-8")
    assert "load_automanager_activity_log_v2" in source
    assert "Hendelser og neste status" in source
    assert "Status nå:" in source
    assert "Neste:" in source
    assert "event.engine" in source
    assert "Realisert netto" in source


def test_execution_panel_separates_exit_from_reentry_authority():
    source = Path("tradingdesk_autotrade_entry_gate_v2.py").read_text(encoding="utf-8")
    assert "Manage-only · automatisk exit, ingen re-entry" in source
    assert "Full auto · automatisk exit + re-entry" in source
    assert "Godkjenn re-entry · automatisk exit" in source
    assert "LONG → EXIT til FLAT på bearish 30m MACD-kryss" in source
    assert "RE-ENTRY LONG på neste bullish kryss" in source
    assert "Arm automatisk LIVE CLOSE" in source
    assert "Arm LIVE re-entry" in source
    assert "Godkjenn denne {direction}-entryen" in source
    assert "approve_open_request_v2" in source
    assert "ENTRY_MODE_MANUAL_ONLY" in source
