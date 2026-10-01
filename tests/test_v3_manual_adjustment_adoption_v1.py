from pathlib import Path


def test_v3_conflict_auto_adopts_only_proven_manual_fill():
    source=Path("autotrader_v3_live_runtime_v1.py").read_text()
    assert "manual_fill_explains_inventory_change_v1" in source
    assert "pending=manual-adopted" in source
    assert "unexplained inventory change" in source
    assert "manual/external inventory change requires acknowledgement" not in source


def test_pending_order_exposes_timestamp_for_manual_fill_window():
    source=Path("autotrader_v3_order_guard_v1.py").read_text()
    assert "submitted_amount,submitted_side,updated_at" in source
