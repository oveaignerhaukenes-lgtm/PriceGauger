from pathlib import Path


def _legacy_source() -> str:
    return Path("autotrader_live_open_legacy_v2.py").read_text(encoding="utf-8")


def test_legacy_live_open_keeps_entry_mode_and_one_shot_approval_compatibility():
    # Simple Core always uses AUTO; the older modes remain internal compatibility
    # contracts and are deliberately not exposed as normal TradingDesk gates.
    source = _legacy_source()
    assert "ENTRY_MODE_MANUAL_ONLY" in source
    assert "ENTRY_MODE_APPROVAL_REQUIRED" in source
    assert "ENTRY_MODE_AUTO" in source
    assert "STATUS_APPROVED" in source
    assert "approve_open_request_v2" in source
    assert "approved_at" in source
    assert "approval_source" in source
    assert "entry_mode == ENTRY_MODE_APPROVAL_REQUIRED and request_status != STATUS_APPROVED" in source


def test_live_open_never_revives_pre_authority_or_superseded_strategy_signal():
    source = _legacy_source()
    assert "_entry_authority_changed_after_request" in source
    assert 'block_reason="ENTRY_AUTHORITY_CHANGED"' in source
    assert "pg_v2_autotrader_strategy_evaluations" in source
    assert "intent_id IS NOT NULL AND signal_at > ?" in source
    assert 'block_reason="NEWER_STRATEGY_SIGNAL"' in source


def test_live_open_reconciles_accepted_orders_even_when_new_open_is_disarmed():
    source = _legacy_source()
    reconcile_index = source.index("if _accepted_attempts():")
    disarm_index = source.index("if not armed:")
    assert reconcile_index < disarm_index
    assert "reconcile_live_open_attempts_v2(client)" in source
    assert "no blind retry" not in source.lower() or "STATUS_UNCERTAIN" in source


def test_simple_core_reentry_waits_for_execution_certainty_not_realized_pnl_settlement():
    facade = Path("autotrader_live_open_v2.py").read_text(encoding="utf-8")
    legacy = _legacy_source()

    assert "P/L reconciliation is accounting" in facade
    assert "status IN ('SUBMITTING', 'UNCERTAIN')" in facade
    assert "status IN ('ORDER_ACCEPTED', 'RECONCILED')" in facade
    assert "_legacy._settled_close_provenance = _execution_close_provenance_v1" in facade

    # The accounting gate is relaxed only after the broker state is independently
    # confirmed FLAT. The hardened engine still blocks any actual product exposure.
    loop_start = legacy.index("for request in candidates:")
    product_block_index = legacy.index('block_reason="PRODUCT_NOT_CONFIRMED_FLAT"', loop_start)
    sizing_index = legacy.index("find_largest_legal_entry_v2(", product_block_index)
    assert product_block_index < sizing_index
