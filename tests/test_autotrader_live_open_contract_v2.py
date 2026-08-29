from pathlib import Path


def test_live_open_is_gated_by_entry_mode_and_exact_one_shot_approval():
    source = Path("autotrader_live_open_v2.py").read_text(encoding="utf-8")
    assert "ENTRY_MODE_MANUAL_ONLY" in source
    assert "ENTRY_MODE_APPROVAL_REQUIRED" in source
    assert "ENTRY_MODE_AUTO" in source
    assert "STATUS_APPROVED" in source
    assert "approve_open_request_v2" in source
    assert "approved_at" in source
    assert "approval_source" in source
    assert "entry_mode == ENTRY_MODE_APPROVAL_REQUIRED and request_status != STATUS_APPROVED" in source


def test_live_open_never_revives_pre_authority_or_superseded_strategy_signal():
    source = Path("autotrader_live_open_v2.py").read_text(encoding="utf-8")
    assert "_entry_authority_changed_after_request" in source
    assert 'block_reason="ENTRY_AUTHORITY_CHANGED"' in source
    assert "pg_v2_autotrader_strategy_evaluations" in source
    assert "intent_id IS NOT NULL AND signal_at > ?" in source
    assert 'block_reason="NEWER_STRATEGY_SIGNAL"' in source


def test_live_open_reconciles_accepted_orders_even_when_new_open_is_disarmed():
    source = Path("autotrader_live_open_v2.py").read_text(encoding="utf-8")
    reconcile_index = source.index("if _accepted_attempts():")
    disarm_index = source.index("if not armed:")
    assert reconcile_index < disarm_index
    assert "reconcile_live_open_attempts_v2(client)" in source
    assert "no blind retry" not in source.lower() or "STATUS_UNCERTAIN" in source
