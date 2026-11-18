"""V3 SQL-tail diagnostics must not alter retry or transaction behavior."""
from __future__ import annotations

from pathlib import Path

import database
import v3_runtime_timing_v1 as timing


class Connection:
    def __init__(self):
        self.calls=[]
        self.commits=0

    def execute(self, sql, params=()):
        self.calls.append((sql,tuple(params)))
        return object()

    def commit(self):
        self.commits+=1

    def rollback(self):
        raise AssertionError("unexpected rollback")

    def close(self):
        raise AssertionError("leased connection must be pooled")


class Pool:
    def __init__(self, connection):
        self.connection=connection
        self.returned=[]

    def getconn(self, **_):
        return self.connection

    def putconn(self, conn):
        self.returned.append(conn)


def test_aggregate_sql_timings_only_and_preserved_commit(monkeypatch):
    conn=Connection()
    pool=Pool(conn)
    phases=[]
    monkeypatch.setattr(database,"using_postgres",lambda:True)
    monkeypatch.setattr(database,"_get_v3_postgres_pool",lambda:pool)
    monkeypatch.setattr(timing,"record_v3_phase_v1",lambda phase,seconds,**_:phases.append((phase,seconds)))
    with database.v3_postgres_pool_scope():
        with database.connect() as db:
            db.execute("SELECT account_secret FROM private_table WHERE key=?",("secret",))
            db.execute("INSERT INTO private_table(key) VALUES (?)",("secret",))
    assert [name for name,_ in phases].count("db_acquire")==1
    assert [name for name,_ in phases].count("db_read")==1
    assert [name for name,_ in phases].count("db_write")==1
    assert [name for name,_ in phases].count("db_finalize")==1
    assert all(isinstance(sec,float) and sec>=0 for _,sec in phases)
    assert conn.commits==1
    assert pool.returned==[conn]


def test_sql_instrumentation_is_not_enabled_for_other_db_users(monkeypatch):
    conn=Connection()
    class Closeable(Connection):
        def close(self):
            pass
    direct=Closeable()
    monkeypatch.setattr(database,"using_postgres",lambda:True)
    monkeypatch.setattr(database.DatabaseConnection,"_open_postgres",lambda self:direct)
    def unexpected(*_args,**_kwargs):
        raise AssertionError("no telemetry outside V3")
    monkeypatch.setattr(timing,"record_v3_phase_v1",unexpected)
    with database.connect() as db:
        db.execute("SELECT 1")
    assert direct.commits==1


def test_account_cycle_p99_and_saxo_guards_remain_present():
    worker=Path("worker.py").read_text()
    runtime=Path("autotrader_v3_live_runtime_v1.py").read_text()
    assert "record_v3_phase_v1('account_cycle',elapsed)" in worker
    assert "record_v3_phase_v1('decision_to_submit'" in runtime
    assert "record_v3_quote_submit_age_v1(decision.decision_key)" in runtime
    assert runtime.index("claim_reserved_for_submission_v3(request_key") < runtime.index(
        "result=broker.place_order(order,confirm_live=True)"
    )
