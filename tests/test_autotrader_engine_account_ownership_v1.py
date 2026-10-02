import sqlite3

import autotrader_engine_account_ownership_v1 as ownership


def _connect(path):
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    return con


def test_v2_and_v3_can_own_different_accounts(monkeypatch, tmp_path):
    db = str(tmp_path / "pg.db")
    monkeypatch.setattr(ownership, "connect", _connect)
    v2 = ownership.claim_account_v1("account-a", "V2", "pilot-v2", db_path=db)
    v3 = ownership.claim_account_v1("account-b", "V3", "pilot-v3", db_path=db)
    assert v2.engine_id == "V2"
    assert v3.engine_id == "V3"


def test_same_account_cannot_acquire_dual_engine_authority(monkeypatch, tmp_path):
    db = str(tmp_path / "pg.db")
    monkeypatch.setattr(ownership, "connect", _connect)
    ownership.claim_account_v1("account-a", "V2", "pilot-v2", db_path=db)
    try:
        ownership.claim_account_v1("account-a", "V3", "pilot-v3", db_path=db)
    except RuntimeError as exc:
        assert "cannot acquire dual authority" in str(exc)
    else:
        raise AssertionError("dual engine ownership must fail closed")


def test_same_owner_claim_is_idempotent_and_transfer_requires_release(monkeypatch, tmp_path):
    db = str(tmp_path / "pg.db")
    monkeypatch.setattr(ownership, "connect", _connect)
    first = ownership.claim_account_v1("account-a", "V3", "pilot-1", db_path=db)
    assert ownership.claim_account_v1("account-a", "V3", "pilot-1", db_path=db) == first
    try:
        ownership.claim_account_v1("account-a", "V3", "pilot-2", db_path=db)
    except RuntimeError as exc:
        assert "explicit release is required" in str(exc)
    else:
        raise AssertionError("implicit owner transfer must fail closed")
    assert ownership.release_account_v1("account-a", "V3", "pilot-1", db_path=db)
    assert ownership.claim_account_v1("account-a", "V2", "pilot-2", db_path=db).engine_id == "V2"
