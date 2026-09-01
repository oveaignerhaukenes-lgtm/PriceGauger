from __future__ import annotations

from pathlib import Path


def test_strategy_switch_is_control_plane_only_and_creates_clean_target_pilot() -> None:
    source = Path("autotrader_strategy_switch_v2.py").read_text(encoding="utf-8")
    assert "enrollment.product.pilot_key(target.key)" in source
    assert "strategy switch requires confirmed FLAT exposure" in source
    assert "strategy switch requires no working Saxo order" in source
    assert "target strategy pilot already has history or partial state" in source
    assert "require_source_settled_flat_provenance_v2" in source
    assert "INSERT INTO pg_v2_autotrader_pilot_equity_state" in source
    assert "UPDATE pg_v2_autotrader_strategy_enrollments" in source
    assert "SET enabled = FALSE, live_open_armed = FALSE" in source
    assert "INSERT INTO pg_v2_autotrader_strategy_enrollments" in source
    assert "INSERT INTO pg_v2_autotrader_margin_configs" in source
    assert "TRUE, FALSE" in source
    assert "UPDATE pg_v2_autotrader_execution_requests" in source
    assert "status = 'SUPERSEDED'" in source
    assert "block_reason = 'STRATEGY_SWITCH'" in source
    assert "DELETE FROM pg_v2_autotrader_strategy_runtime_state" in source
    assert "DELETE FROM pg_v2_autotrader_live_pilot_state" in source
    assert "DELETE FROM pg_v2_autotrader_mtf_live_state" in source
    assert "DELETE FROM pg_v2_autotrader_mtf_short_live_state" in source
    assert "settled_flat_provenance" in source
    assert "source_close_event_id" in source
    assert "_post_once" not in source
    assert "trade/v2/orders" not in source


def test_strategy_switch_quiesces_before_external_validation_and_uses_fk_safe_order() -> None:
    source = Path("autotrader_strategy_switch_v2.py").read_text(encoding="utf-8")
    quiesce = source.index("_quiesce_source_open_authority_v2(enrollment)")
    flat = source.index("_confirmed_flat_v2(enrollment)")
    provenance = source.index("require_source_settled_flat_provenance_v2(enrollment)")
    equity = source.index("INSERT INTO pg_v2_autotrader_pilot_equity_state")
    enrollment = source.index("INSERT INTO pg_v2_autotrader_strategy_enrollments")
    margin = source.index("INSERT INTO pg_v2_autotrader_margin_configs")
    assert quiesce < flat < provenance
    assert equity < enrollment < margin


def test_strategy_switch_never_adopts_open_exposure_between_strategy_cohorts() -> None:
    source = Path("autotrader_strategy_switch_v2.py").read_text(encoding="utf-8")
    assert "_confirmed_flat_v2(enrollment)" in source
    assert "currently observed {observed}" in source
    assert 'enrollment.account_id,\n                "",' in source
    assert 'observed_direction="FLAT"' in source


def test_live_open_accepts_only_audited_one_shot_flat_handoff_and_rechecks_before_submit() -> None:
    source = Path("autotrader_live_open_v2.py").read_text(encoding="utf-8")
    assert "has_unconsumed_settled_flat_handoff_v2" in source
    assert "_submit_authority_still_current" in source
    final_precheck = source.index("final = precheck_entry_amount_v2")
    final_authority = source.index("if not _submit_authority_still_current(request)")
    durable_attempt = source.index("if not _record_attempt_before_submit")
    post = source.index('response = _post_once(client, "trade/v2/orders", order_payload)')
    assert final_precheck < final_authority < durable_attempt < post
    assert "fresh_positions = _product_positions" in source
    assert source.count("_open_orders_exist(client, account_key=account_key, uic=enrollment.uic)") >= 2


def test_entry_gate_exposes_explicit_strategy_switch_and_disarms_open() -> None:
    source = Path("tradingdesk_autotrade_entry_gate_v2.py").read_text(encoding="utf-8")
    assert "AUTOTRADER_STRATEGIES_V2" in source
    assert "switch_live_strategy_v2" in source
    assert '"Bytt LIVE-strategi"' in source
    assert "Selve byttet sender ingen ordre" in source
    assert "LIVE OPEN/re-entry blir disarmed" in source
    assert "st.rerun()" in source
