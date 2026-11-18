"""Schema DDL is a one-time PostgreSQL bootstrap, not per-quote work."""
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from time import sleep
from types import SimpleNamespace

import pytest

import database
import autotrader_v3_closed_bar_driver_v1 as closed
import autotrader_v3_live_runtime_v1 as live


def _pg(monkeypatch, name="schema-test"):
    monkeypatch.setattr(database, "using_postgres", lambda: True)
    monkeypatch.setattr(database, "database_url", lambda: "postgres://"+name)


def test_schema_single_flight_waits_for_successful_initializer(monkeypatch):
    _pg(monkeypatch,"schema-singleflight")
    calls=[]
    lock=Lock()

    def initialize():
        with lock:
            calls.append("start")
        sleep(0.025)
        with lock:
            calls.append("complete")

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(
            lambda _: database.run_postgres_schema_once_v1("live/singleflight",initialize),
            range(16),
        ))
    assert calls==["start","complete"]


def test_failed_initialization_is_not_cached(monkeypatch):
    _pg(monkeypatch,"schema-retry-after-error")
    attempts=[]

    def initialize():
        attempts.append(1)
        if len(attempts)==1:
            raise RuntimeError("initialization transaction failed")

    with pytest.raises(RuntimeError):
        database.run_postgres_schema_once_v1("live/schema-error",initialize)
    database.run_postgres_schema_once_v1("live/schema-error",initialize)
    database.run_postgres_schema_once_v1("live/schema-error",initialize)
    assert len(attempts)==2


def test_schema_cache_isolated_by_database_identity(monkeypatch):
    _pg(monkeypatch,"schema-database-one")
    seen=[]
    database.run_postgres_schema_once_v1("live/db-identity",lambda:seen.append("one"))
    monkeypatch.setattr(database,"database_url",lambda:"postgres://schema-database-two")
    database.run_postgres_schema_once_v1("live/db-identity",lambda:seen.append("two"))
    assert seen==["one","two"]


def test_sqlite_schema_initializes_every_time(monkeypatch):
    monkeypatch.setattr(database,"using_postgres",lambda:False)
    count=[]
    database.run_postgres_schema_once_v1("sqlite-should-not-cache",lambda:count.append(1))
    database.run_postgres_schema_once_v1("sqlite-should-not-cache",lambda:count.append(1))
    assert len(count)==2


def test_closed_bar_schema_uses_one_committed_postgres_initialization(monkeypatch):
    _pg(monkeypatch,"schema-closed-bar")
    writes=[]
    monkeypatch.setattr(closed,"_ensure_closed_bar_driver_schema_uncached_v3",
                        lambda db_path:writes.append(str(db_path)))
    closed.ensure_closed_bar_driver_schema_v3("ignored.pg")
    closed.ensure_closed_bar_driver_schema_v3("ignored.pg")
    assert writes==["ignored.pg"]


class FakeDB:
    def __init__(self,queries):
        self.queries=queries
    def __enter__(self):
        return self
    def __exit__(self,*_):
        return False
    def execute(self,sql,params=()):
        self.queries.append(sql)
        # An existing stable LIVE strategy context should never trigger reset.
        return SimpleNamespace(fetchone=lambda:{"strategy_key":"same","timeframe_minutes":1})


def test_runtime_status_ddl_once_but_live_updates_never_skipped(monkeypatch):
    _pg(monkeypatch,"schema-runtime-state")
    monkeypatch.setattr(live,"using_postgres",lambda:True)
    queries=[]
    monkeypatch.setattr(live,"connect",lambda *_:FakeDB(queries))
    live._record_runtime("trader","READY","one")
    live._record_runtime("trader","MANAGING","two")
    assert len([q for q in queries if "CREATE TABLE IF NOT EXISTS" in q])==1
    assert len([q for q in queries if "INSERT INTO autotrader_v3_live_runtime_state" in q])==2


def test_decision_context_schema_once_with_each_live_evaluation(monkeypatch):
    _pg(monkeypatch,"schema-context-state")
    monkeypatch.setattr(live,"using_postgres",lambda:True)
    monkeypatch.setattr(live,"ensure_closed_bar_driver_schema_v3",lambda *_:None)
    queries=[]
    monkeypatch.setattr(live,"connect",lambda *_:FakeDB(queries))
    assert not live._prepare_live_decision_context_v3(
        trader_id="t",strategy_key="same",timeframe_minutes=1,
        actual_amount=0,db_path="ignored.db")
    assert not live._prepare_live_decision_context_v3(
        trader_id="t",strategy_key="same",timeframe_minutes=1,
        actual_amount=0,db_path="ignored.db")
    assert len([q for q in queries if "CREATE TABLE IF NOT EXISTS" in q])==1
    assert len([q for q in queries if "INSERT INTO autotrader_v3_live_decision_context" in q])==2
