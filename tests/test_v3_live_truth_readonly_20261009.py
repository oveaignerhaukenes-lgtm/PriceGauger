"""Read-only V3 instance status must never confuse inferred state and Saxo truth."""
from dataclasses import FrozenInstanceError
import pytest

from autotrader_v3_live_truth_v1 import (
    _reason, inventory_label_v1, load_v3_live_truth_v1,
)
from database import connect


def test_v3_status_never_infers_unreported_target_or_inventory():
    assert inventory_label_v1(None) == "ukjent"
    assert inventory_label_v1(0.0) == "FLAT 0 lot"
    assert inventory_label_v1(-0.02) == "SHORT 0.02 lot"
    assert inventory_label_v1(0.01) == "LONG 0.01 lot"
    assert "kapitalgrense" in _reason("MANAGING", "PG capital cap reached; holding SHORT actual=-0.02")


def test_read_only_status_scopes_execution_by_instance_account_and_instrument(tmp_path):
    db = str(tmp_path / "truth.sqlite")
    with connect(db) as conn:
        conn.execute("""CREATE TABLE autotrader_v3_live_runtime_state(
            trader_id TEXT PRIMARY KEY,status TEXT,detail TEXT,updated_at TEXT)""")
        conn.execute("""CREATE TABLE autotrader_v3_execution_events(
            request_key TEXT PRIMARY KEY,instance_id TEXT,account_id TEXT,uic INTEGER,
            asset_type TEXT,action TEXT,side TEXT,amount REAL,executed_at TEXT)""")
        conn.execute("""INSERT INTO autotrader_v3_live_runtime_state VALUES (
            'five-min','MANAGING','target=-0.02 actual=-0.02','2026-10-09T09:21:10Z')""")
        conn.execute("""INSERT INTO autotrader_v3_execution_events VALUES
            ('correct','five-min','acct-5',4912,'CfdOnIndex','ADD','Sell',0.01,'2026-10-09T09:05:46Z')""")
        conn.execute("""INSERT INTO autotrader_v3_execution_events VALUES
            ('other','five-min','acct-OTHER',4912,'CfdOnIndex','CLOSE','Buy',0.03,'2026-10-09T09:10:10Z')""")
        conn.execute("""INSERT INTO autotrader_v3_execution_events VALUES
            ('other-product','five-min','acct-5',8000,'CfdOnIndex','OPEN','Buy',0.03,'2026-10-09T09:15:00Z')""")
    model = load_v3_live_truth_v1(
        instance_id="five-min", account_id="acct-5", uic=4912,
        asset_type="CfdOnIndex", db_path=db,
    )
    assert model.actual == pytest.approx(-0.02)
    assert model.target == pytest.approx(-0.02)
    assert model.status == "MANAGING"
    assert model.last_execution == "ADD Sell 0.01 lot · 2026-10-09T09:05:46Z"
    assert model.updated_at == "2026-10-09T09:21:10Z"
    with pytest.raises(FrozenInstanceError):
        model.status = "ON"


def test_blocked_heartbeat_shows_cap_hold_without_inventing_target(tmp_path):
    db = str(tmp_path / "cap.sqlite")
    with connect(db) as conn:
        conn.execute("""CREATE TABLE autotrader_v3_live_runtime_state(
            trader_id TEXT PRIMARY KEY,status TEXT,detail TEXT,updated_at TEXT)""")
        conn.execute("""INSERT INTO autotrader_v3_live_runtime_state VALUES(
            'five-min','MANAGING',
            'PG capital cap reached; holding SHORT actual=-0.02; same-direction OPEN/ADD paused',
            '2026-10-09T09:10:20Z')""")
    model = load_v3_live_truth_v1(
        instance_id="five-min", account_id="acct-5", uic=4912,
        asset_type="CfdOnIndex", db_path=db,
    )
    assert model.actual == -0.02
    assert model.target is None
    assert model.last_execution is None
    assert "kapitalgrense" in model.reason


def test_missing_heartbeat_stays_unknown(tmp_path):
    db = str(tmp_path / "empty.sqlite")
    model = load_v3_live_truth_v1(
        instance_id="missing", account_id="acct", uic=4912,
        asset_type="CfdOnIndex", db_path=db,
    )
    assert model.status == "UNKNOWN"
    assert model.actual is None and model.target is None
