from pathlib import Path

def test_v3_live_runtime_parses_saxo_account_rows_as_dicts():
    text=Path("autotrader_v3_live_runtime_v1.py").read_text(encoding="utf-8")
    assert 'row.get("AccountId")' in text
    assert 'row.get("AccountKey")' in text
    assert "a.account_id" not in text
    assert "account.account_key" not in text
