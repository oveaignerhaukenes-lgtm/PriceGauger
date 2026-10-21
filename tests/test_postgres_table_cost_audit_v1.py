"""Postgres cost audit does not access user data or perform writes."""
from pathlib import Path
import postgres_table_cost_audit_v1 as audit


def test_sql_audit_is_read_only_bounded_and_uses_pg_stats(monkeypatch):
    query = {}
    class DummyDB:
        def __enter__(self): return self
        def __exit__(self,*_args): return False
        def execute(self,sql,args):
            query.update(sql=sql,args=args)
            return type("Result",(),{"fetchall":lambda self:[{
                "name":"pg_v2_market_bars_1m",
                "bytes":3000000,
                "index_bytes":400000,
                "estimated_live_rows":10000,
                "estimated_dead_rows":50,
            }]})()
    monkeypatch.setattr(audit,"using_postgres",lambda:True)
    monkeypatch.setattr(audit,"connect",lambda *_args:DummyDB())
    rows=audit.largest_relations_v1(limit=999)
    assert query["args"]==(20,)
    assert "pg_stat_user_tables" in query["sql"]
    assert not any(term in query["sql"].upper() for term in (
        "DELETE","TRUNCATE","DROP ","UPDATE ","INSERT "))
    assert rows[0]["name"]=="pg_v2_market_bars_1m"
    assert rows[0]["dead_estimate"]==50


def test_sqlite_has_no_pg_catalog_query(monkeypatch):
    monkeypatch.setattr(audit,"using_postgres",lambda:False)
    monkeypatch.setattr(audit,"connect",lambda *_args:1/0)
    assert audit.largest_relations_v1()==()


def test_audit_runtime_is_on_multiworker_telemetry_not_live_loop():
    text=Path("telegram_multi_worker.py").read_text()
    assert "largest_relations_v1" in text
    assert "next_table_audit" in text
    assert "V3_LIVE_INTERVAL_SECONDS" in text
    assert "run_v3_live_fast_loop_v1" in text
