from pathlib import Path

def test_v3_live_runtime_parses_saxo_account_rows_as_dicts():
    text=Path("autotrader_v3_live_runtime_v1.py").read_text(encoding="utf-8")
    assert 'row.get("AccountId")' in text
    assert 'row.get("AccountKey")' in text
    assert "a.account_id" not in text
    assert "account.account_key" not in text


def test_pending_order_reconciliation_uses_exact_position_not_audit_history():
    text=Path("autotrader_v3_live_runtime_v1.py").read_text(encoding="utf-8")
    assert "expected=pending.get('expected_inventory')" in text
    assert "fresh_observations=_position_observations_v2(broker.client)" in text
    assert "abs(fresh_actual.amount-expected_amount) <= 1e-9" in text
    assert "state='RECONCILED'" in text
    assert "no retry sent" in text
    assert "reconcile_pending_v3" not in text
    assert "FinalFill" not in text
    assert "client_key_missing" not in text
    assert "broker_order_id_missing" not in text
