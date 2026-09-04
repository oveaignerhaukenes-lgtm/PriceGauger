from __future__ import annotations

from pathlib import Path


def test_strategy_switch_is_control_plane_only_and_preserves_open_exposure() -> None:
    source = Path("autotrader_strategy_switch_v2.py").read_text(encoding="utf-8")
    assert "enrollment.product.pilot_key(target.key)" in source
    assert "_observed_product_state_v2(enrollment)" in source
    assert "strategy switch requires confirmed FLAT exposure" not in source
    assert "OPEN_POSITION_STRATEGY_HANDOFF" in source
    assert "CONFIRMED_FLAT_STRATEGY_HANDOFF" in source
    assert "anchor = \"\" if observed is None else observed.net_position_id" in source
    assert "SET enabled = FALSE, live_open_armed = FALSE" in source
    assert "status = 'SUPERSEDED'" in source
    assert "block_reason = 'STRATEGY_SWITCH'" in source
    assert "_post_once" not in source


def test_strategy_switch_records_a_non_settling_performance_mark() -> None:
    source = Path("autotrader_strategy_switch_v2.py").read_text(encoding="utf-8")
    assert "pg_v2_autotrader_strategy_switch_marks" in source
    assert "observed_net_position_id" in source
    assert "observed_average_open_price" in source
    assert "observed_mark_price" in source
    assert "observed_pnl_pct" in source
    assert "not synthesize a close" in source


def test_strategy_switch_only_blocks_real_execution_ambiguity() -> None:
    source = Path("autotrader_strategy_switch_v2.py").read_text(encoding="utf-8")
    assert "_pg_execution_inflight_v2(enrollment)" in source
    assert "strategy switch waits while PriceGauger execution is already in flight" in source
    assert "strategy switch waits while a Saxo order is working on this product" in source
    assert source.index("_quiesce_source_authority_v2(enrollment)") < source.index(
        "_observed_product_state_v2(enrollment)"
    )


def test_flat_switch_still_authorizes_first_open_without_waiting_for_old_pnl() -> None:
    source = Path("autotrader_strategy_switch_v2.py").read_text(encoding="utf-8")
    provenance = Path("autotrader_strategy_switch_provenance_v2.py").read_text(encoding="utf-8")
    live_open = Path("autotrader_live_open_v2.py").read_text(encoding="utf-8")
    assert "flat_handoff = observed is None" in source
    assert "settled_flat_provenance" in source
    assert "has_unconsumed_settled_flat_handoff_v2" in provenance
    assert "has_unconsumed_settled_flat_handoff_v2" in live_open


def test_live_open_rechecks_authority_and_broker_state_before_submit() -> None:
    # Simple Core changes only the FLAT provenance helper. The hardened execution
    # engine still performs final authority, exposure and working-order rechecks.
    source = Path("autotrader_live_open_legacy_v2.py").read_text(encoding="utf-8")
    assert "_submit_authority_still_current" in source
    assert "precheck_entry_amount_v2" in source
    assert "_record_attempt_before_submit" in source
    assert "fresh_positions = _product_positions" in source
    assert source.count("_open_orders_exist(client, account_key=account_key, uic=enrollment.uic)") >= 2


def test_simple_core_exposes_direct_strategy_switch_without_confirmation_button() -> None:
    source = Path("tradingdesk_automanager_simple_v1.py").read_text(encoding="utf-8")
    assert "AUTOTRADER_STRATEGIES_V2" in source
    assert "switch_live_strategy_v2" in source
    assert "selected_strategy = st.selectbox" in source
    assert "selected_strategy.key != enrollment.strategy_key" in source
    assert "st.rerun()" in source
    assert "Jeg vil at PriceGauger skal AutoManage" not in source
