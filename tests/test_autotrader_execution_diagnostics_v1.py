from autotrader_engine_account_ownership_v1 import claim_account_v1
from autotrader_execution_diagnostics_v1 import load_execution_diagnostic_v1
from database import connect


def test_diagnostic_joins_owner_runtime_and_latest_request(tmp_path):
    db_path = str(tmp_path / "pg.db")
    claim_account_v1("acct", "V3", "pilot", db_path=db_path)
    with connect(db_path) as db:
        db.execute("""CREATE TABLE autotrader_v3_live_runtime_state(
            trader_id TEXT PRIMARY KEY,status TEXT,detail TEXT,updated_at TEXT)""")
        db.execute("INSERT INTO autotrader_v3_live_runtime_state VALUES(?,?,?,?)",
                   ("pilot", "READY", "actual=0.01 target=0.02", "2026-10-02 09:00:00"))
        db.execute("""CREATE TABLE autotrader_v3_order_guard(
            request_key TEXT,state TEXT,broker_order_id TEXT,expected_inventory REAL,
            submitted_amount REAL,submitted_side TEXT,detail TEXT,updated_at TEXT,
            account_id TEXT,uic INTEGER,asset_type TEXT)""")
        db.execute("INSERT INTO autotrader_v3_order_guard VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                   ("req-1", "SUBMITTED", "broker-7", 0.02, 0.01, "Buy", "accepted",
                    "2026-10-02 09:00:01", "acct", 4912, "CfdOnIndex"))

    item = load_execution_diagnostic_v1(
        account_id="acct", uic=4912, asset_type="CfdOnIndex",
        owner_key="pilot", engine_id="V3", db_path=db_path,
    )
    assert item.runtime_status == "READY"
    assert item.request_key == "req-1"
    assert item.request_state == "SUBMITTED"
    assert item.broker_order_id == "broker-7"
    assert item.expected_inventory == 0.02


def test_diagnostic_fails_closed_on_owner_mismatch(tmp_path):
    db_path = str(tmp_path / "pg.db")
    claim_account_v1("acct", "V3", "pilot-a", db_path=db_path)
    try:
        load_execution_diagnostic_v1(
            account_id="acct", uic=4912, asset_type="CfdOnIndex",
            owner_key="pilot-b", engine_id="V3", db_path=db_path,
        )
    except RuntimeError as exc:
        assert "boundary mismatch" in str(exc)
    else:
        raise AssertionError("diagnostics must not cross an ownership boundary")


def test_diagnostic_tolerates_missing_runtime_tables(tmp_path):
    db_path = str(tmp_path / "pg.db")
    item = load_execution_diagnostic_v1(
        account_id="acct", uic=4912, asset_type="CfdOnIndex",
        owner_key="pilot", engine_id="V3", db_path=db_path,
    )
    assert item.runtime_status is None
    assert item.request_key is None
