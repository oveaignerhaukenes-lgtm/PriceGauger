from __future__ import annotations

from pathlib import Path


def test_strategy_switch_is_control_plane_only_and_preserves_open_exposure() -> None:
    source = Path("autotrader_strategy_switch_v2.py").read_text(encoding="utf-8")
    assert "enrollment.product.pilot_key(target.key)" in source
    assert "_observed_product_state_v2(enrollment)" in source
    assert "strategy switch requires confirmed FLAT exposure" not in source
    assert "require_source_settled_flat_provenance_v2" not in source
    assert "OPEN_POSITION_STRATEGY_HANDOFF" in source
    assert "CONFIRMED_FLAT_STRATEGY_HANDOFF" in source
    assert "anchor = \"\" if observed is None else observed.net_position_id" in source
    assert "enrollment.entry_mode == ENTRY_MODE_AUTO or enrollment.live_open_armed" in source
    assert "INSERT INTO pg_v2_autotrader_pilot_equity_state" in source
    assert "UPDATE pg_v2_autotrader_strategy_enrollments" in source
    assert "SET enabled = FALSE, live_open_armed = FALSE" in source
    assert "INSERT INTO pg_v2_autotrader_strategy_enrollments" in source
    assert "INSERT INTO pg_v2_autotrader_margin_configs" in source
    assert "UPDATE pg_v2_autotrader_execution_requests" in source
    assert "status = 'SUPERSEDED'" in source
    assert "block_reason = 'STRATEGY_SWITCH'" in source
    assert "_post_once" not in source
    assert "trade/v2/orders" not in source


def test_strategy_switch_records_a_non_settling_performance_mark() -> None:
    source = Path("autotrader_strategy_switch_v2.py").read_text(encoding="utf-8")
    assert "pg_v2_autotrader_strategy_switch_marks" in source
    assert "observed_net_position_id" in source
    assert "observed_average_open_price" in source
    assert "observed_mark_price" in source
    assert "observed_pnl_pct" in source
    assert "not synthesize a close" in source
    assert "never fabricates a" in source


def test_strategy_switch_only_blocks_real_execution_ambiguity() -> None:
    source = Path("autotrader_strategy_switch_v2.py").read_text(encoding="utf-8")
    assert "_pg_execution_inflight_v2(enrollment)" in source
    assert "strategy switch waits while PriceGauger execution is already in flight" in source
    assert "strategy switch waits while a Saxo order is working on this product" in source
    quiesce = source.index("_quiesce_source_authority_v2(enrollment)")
    observe = source.index("_observed_product_state_v2(enrollment)")
    equity = source.index("INSERT INTO pg_v2_autotrader_pilot_equity_state")
    enrollment = source.index("INSERT INTO pg_v2_autotrader_strategy_enrollments")
    margin = source.index("INSERT INTO pg_v2_autotrader_margin_configs")
    assert quiesce < observe
    assert equity < enrollment < margin


def test_flat_switch_still_authorizes_first_open_without_waiting_for_old_pnl() -> None:
    source = Path("autotrader_strategy_switch_v2.py").read_text(encoding="utf-8")
    provenance = Path("autotrader_strategy_switch_provenance_v2.py").read_text(encoding="utf-8")
    live_open = Path("autotrader_live_open_v2.py").read_text(encoding="utf-8")
    assert "flat_handoff = observed is None" in source
    assert "settled_flat_provenance" in source
    assert "has_unconsumed_settled_flat_handoff_v2" in provenance
    assert "has_unconsumed_settled_flat_handoff_v2" in live_open


def test_live_open_rechecks_before_submit() -> None:
    source = Path("autotrader_live_open_v2.py").read_text(encoding="utf-8")
    assert "_submit_authority_still_current" in source
    final_precheck = source.index("final = precheck_entry_amount_v2")
    final_authority = source.index("if not _submit_authority_still_current(request)")
    durable_attempt = source.index("if not _record_attempt_before_submit")
    post = source.index('response = _post_once(client, "trade/v2/orders", order_payload)')
    assert final_precheck < final_authority < durable_attempt < post
    assert "fresh_positions = _product_positions" in source
    assert source.count("_open_orders_exist(client, account_key=account_key, uic=enrollment.uic)") >= 2


def test_entry_gate_exposes_direct_strategy_switch() -> None:
    source = Path("tradingdesk_autotrade_entry_gate_v2.py").read_text(encoding="utf-8")
    assert "AUTOTRADER_STRATEGIES_V2" in source
    assert "switch_live_strategy_v2" in source
    assert '"LIVE-strategi"' in source
    assert "Bytt LIVE-strategi direkte i listen" in source
    assert "Selve byttet sender ingen ordre" in source
    switch_start = source.index("def _render_strategy_switch")
    switch_end = source.index("def _render_armed_badge")
    switch_source = source[switch_start:switch_end]
    assert "st.checkbox" not in switch_source
    assert '"Bytt LIVE-strategi",' not in switch_source
    assert "st.rerun()" in switch_source
