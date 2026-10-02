from pathlib import Path


def test_v3_conflict_adopts_exact_live_account_instrument_inventory():
    source=Path("autotrader_v3_live_runtime_v1.py").read_text()
    assert "LIVE account+instrument inventory adopted" in source
    assert "pending=inventory-adopted" in source
    assert "manual_fill_explains_inventory_change_v1" not in source
    assert "unexplained inventory change" not in source


def test_adopted_oversize_inventory_keeps_reduction_authority_separate_from_expansion():
    source=Path("autotrader_v3_live_runtime_v1.py").read_text()
    adoption=source.index("LIVE account+instrument inventory adopted")
    reduction=source.index("if mutation.action in {'REDUCE','CLOSE'}")
    expansion=source.index("if mutation.action in {'OPEN','ADD'}")
    policy=source.index("load_execution_policy_v3", expansion)
    assert adoption < reduction < expansion < policy
    assert "Reduction exceeds exact current position" in source
    assert "OPEN/ADD requires an explicit V3 NOK exposure policy" in source


def test_pending_order_exposes_timestamp_for_reconciliation_history():
    source=Path("autotrader_v3_order_guard_v1.py").read_text()
    assert "submitted_amount,submitted_side,updated_at" in source
