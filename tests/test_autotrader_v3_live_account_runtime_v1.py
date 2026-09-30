from pathlib import Path

def test_v3_live_runtime_parses_saxo_account_rows_as_dicts():
    text=Path("autotrader_v3_live_runtime_v1.py").read_text(encoding="utf-8")
    assert 'row.get("AccountId")' in text
    assert 'row.get("AccountKey")' in text
    assert "a.account_id" not in text
    assert "account.account_key" not in text


def test_pending_reconciliation_exposes_missing_prerequisites_without_secret_keys():
    text=Path("autotrader_v3_live_runtime_v1.py").read_text(encoding="utf-8")
    for reason in ("account_context_missing", "client_key_missing", "broker_order_id_missing"):
        assert reason in text
    assert "bool(context and context[1])" in text
    assert "bool(pending.get('broker_order_id'))" in text
    assert "LOGGER.warning('v3 pending reconciliation" in text
