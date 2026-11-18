"""Isolate PostgreSQL reuse to V3 accounts without weakening transaction safety."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Lock
from types import SimpleNamespace

import pytest

import database
import v3_runtime_timing_v1 as timing


class FakeConnection:
    def __init__(self, *, fail_select=False, fail_write=False):
        self.closed_count=0
        self.commits=0
        self.rollbacks=0
        self.executed=[]
        self.fail_select=fail_select
        self.fail_write=fail_write

    def execute(self, sql, parameters=()):
        self.executed.append((sql,tuple(parameters)))
        if self.fail_select and sql.upper().startswith("SELECT"):
            raise RuntimeError("read connection lost")
        if self.fail_write and sql.upper().startswith("INSERT"):
            raise RuntimeError("write connection lost")
        return "OK"

    def commit(self):
        self.commits+=1

    def rollback(self):
        self.rollbacks+=1

    def close(self):
        self.closed_count+=1


class FakePool:
    def __init__(self,*conns):
        self.connections=list(conns)
        self.leased=[]
        self.returned=[]
        self.lock=Lock()

    def getconn(self, *, timeout=None):
        with self.lock:
            if not self.connections:
                raise RuntimeError("PostgreSQL pool exhausted")
            conn=self.connections.pop(0)
            self.leased.append(conn)
            return conn

    def putconn(self,conn):
        with self.lock:
            self.returned.append(conn)


@pytest.fixture
def postgres(monkeypatch):
    monkeypatch.setattr(database,"using_postgres",lambda:True)


def test_postgres_pool_is_off_outside_v3_account_scope(postgres,monkeypatch):
    direct=FakeConnection()
    monkeypatch.setattr(database.DatabaseConnection,"_open_postgres",lambda self:direct)
    monkeypatch.setattr(database,"_get_v3_postgres_pool",
                        lambda: (_ for _ in ()).throw(AssertionError("pool should be off")))
    with database.connect("legacy.db") as db:
        assert db._postgres_pool is None
        assert db.execute("SELECT value FROM table") == "OK"
    assert direct.commits==1
    assert direct.closed_count==1


def test_v3_pool_commits_and_returns_without_closing(postgres,monkeypatch):
    conn=FakeConnection()
    pool=FakePool(conn)
    monkeypatch.setattr(database,"_get_v3_postgres_pool",lambda:pool)
    with database.v3_postgres_pool_scope():
        with database.connect("legacy.db") as db:
            assert db._postgres_pool is pool
            assert db.execute("SELECT value FROM sample WHERE id=?",(7,))=="OK"
    assert conn.executed==[("SELECT value FROM sample WHERE id=%s",(7,))]
    assert conn.commits==1
    assert conn.closed_count==0
    assert pool.returned==[conn]
    assert not database._V3_POSTGRES_POOL_ENABLED.get()


def test_v3_pool_rolls_back_and_returns_on_failure(postgres,monkeypatch):
    conn=FakeConnection(fail_write=True)
    pool=FakePool(conn)
    monkeypatch.setattr(database,"_get_v3_postgres_pool",lambda:pool)
    with database.v3_postgres_pool_scope():
        with pytest.raises(RuntimeError,match="write connection lost"):
            with database.connect() as db:
                db.execute("INSERT INTO orders VALUES (?)",("once",))
    assert conn.rollbacks==1
    assert conn.commits==0
    assert len(conn.executed)==1  # no retry of an unsafe INSERT
    assert pool.returned==[conn]


def test_v3_pool_broken_read_replaces_connection_once(postgres,monkeypatch):
    broken=FakeConnection(fail_select=True)
    replacement=FakeConnection()
    pool=FakePool(broken,replacement)
    monkeypatch.setattr(database,"_get_v3_postgres_pool",lambda:pool)
    with database.v3_postgres_pool_scope():
        with database.connect() as db:
            assert db.execute("SELECT value FROM table WHERE id=?",(1,))=="OK"
    assert broken.closed_count==1
    assert replacement.commits==1
    assert pool.returned==[broken,replacement]
    assert len(pool.leased)==2


def test_pool_exhaustion_fails_closed_and_resets_scope(postgres,monkeypatch):
    pool=FakePool()
    monkeypatch.setattr(database,"_get_v3_postgres_pool",lambda:pool)
    with pytest.raises(RuntimeError,match="pool exhausted"):
        with database.v3_postgres_pool_scope():
            with database.connect():
                pass
    assert not database._V3_POSTGRES_POOL_ENABLED.get()


def test_scope_not_inherited_by_unrelated_threads(postgres,monkeypatch):
    direct=FakeConnection()
    pooled=FakeConnection()
    pool=FakePool(pooled)
    monkeypatch.setattr(database.DatabaseConnection,"_open_postgres",lambda self:direct)
    monkeypatch.setattr(database,"_get_v3_postgres_pool",lambda:pool)
    def unscoped():
        with database.connect() as db:
            return db._postgres_pool
    with database.v3_postgres_pool_scope():
        with ThreadPoolExecutor(max_workers=1) as executor:
            other=executor.submit(unscoped).result()
        with database.connect() as db:
            own=db._postgres_pool
    assert other is None
    assert own is pool


def test_v3_pool_only_via_account_task_wrapper(monkeypatch):
    import worker
    calls=[]
    monkeypatch.setattr(worker,"run_v3_live_cycle_v1",
                        lambda **kwargs: calls.append(
                            (kwargs, database._V3_POSTGRES_POOL_ENABLED.get())) or 2)
    result=worker._run_v3_live_pooled_account_v1(account_ids=("A",),hyper_quote_only=True)
    assert result==2
    assert calls==[({"account_ids":("A",),"hyper_quote_only":True},True)]
    assert database._V3_POSTGRES_POOL_ENABLED.get() is False


def test_quote_submit_age_and_tail_percentiles(caplog,monkeypatch):
    monkeypatch.setattr(timing,"_STARTED",timing.time.monotonic())
    timing._SAMPLES.clear()
    stamp=datetime(2026,11,18,22,0,0,tzinfo=timezone.utc)
    timing.record_v3_quote_submit_age_v1(
        f"tick:impulse-catcher-long-v1-1:{(stamp-timedelta(seconds=2)).isoformat()}:TICK_LONG",
        now=stamp)
    assert timing._SAMPLES["quote_to_submit"]==[2.0]
    monkeypatch.setattr(timing,"_STARTED",100.0)
    with caplog.at_level("INFO"):
        timing.record_v3_phase_v1("db_acquire",0.01,now=101)
        timing.record_v3_phase_v1("db_acquire",0.02,now=161)
    assert "p95_ms=" in caplog.text
    assert "p99_ms=" in caplog.text
    assert "quote_to_submit:n=1" in caplog.text
