"""Read-only Saxo quota dashboard: observed traffic, persistence, privacy."""
from __future__ import annotations

from datetime import datetime, timezone
import json

import pytest

import saxo_rest_telemetry_v1 as telemetry
import saxo_rest_quota_dashboard_v1 as dashboard


@pytest.fixture(autouse=True)
def reset_process_metrics(monkeypatch):
    monkeypatch.setattr(telemetry, "_STARTED", 100.0)
    for name in (
        "_COUNTS", "_RATE_LIMITED", "_RATE_REMAINING",
        "_ORIGIN_COUNTS", "_ORIGIN_RATE_LIMITED",
        "_LATENCY_SECONDS", "_QUOTA_HEADERS", "_OUTBOX",
    ):
        getattr(telemetry, name).clear()
    yield
    for name in (
        "_COUNTS", "_RATE_LIMITED", "_RATE_REMAINING",
        "_ORIGIN_COUNTS", "_ORIGIN_RATE_LIMITED",
        "_LATENCY_SECONDS", "_QUOTA_HEADERS", "_OUTBOX",
    ):
        getattr(telemetry, name).clear()


def test_saxo_headers_and_endpoint_counts_persist_without_secret(tmp_path):
    db_path = tmp_path / "saxo-usage.db"
    headers = {
        "X-RateLimit-Session-Limit": "120",
        "x-ratelimit-session-remaining": "75",
        "X-RateLimit-Session-Reset": "42",
        "X-RateLimit-AppDay-Limit": "10000000",
        "X-RateLimit-AppDay-Remaining": "9997000",
        "X-RateLimit-AppDay-Reset": "30000",
    }
    telemetry.record_saxo_http_v1(
        "GET", "port/v1/accounts/me?AccountKey=very-private", 200,
        headers=headers, now=101.0,
    )
    telemetry.record_saxo_http_v1(
        "GET", "port/v1/accounts/me?AccountKey=very-private", 200,
        now=120.0,
    )
    telemetry.record_saxo_http_v1(
        "POST", "trade/v2/orders?OrderId=never-save", 429,
        headers={"X-RateLimit-Session-Remaining": "0"}, now=161.0,
    )

    assert dashboard.flush_saxo_rest_usage_v1(db_path=db_path) == 2
    assert dashboard.flush_saxo_rest_usage_v1(db_path=db_path) == 0
    loaded = dashboard.load_saxo_rest_usage_v1(
        db_path=db_path, minutes=15, now=datetime.now(timezone.utc),
    )
    summary = dashboard.summarize_saxo_rest_usage_v1(loaded)
    assert summary["calls"] == 3
    assert summary["http429"] == 1
    assert summary["endpoints"] == (
        {"method": "GET", "endpoint": "port/v1/accounts", "calls": 2, "http429": 0},
        {"method": "POST", "endpoint": "trade/v2/orders", "calls": 1, "http429": 1},
    )
    by_dimension = {row["dimension"]: row for row in summary["quotas"]}
    assert by_dimension["session"]["used_pct"] == 37.5
    assert by_dimension["session"]["reset_seconds"] == 42
    assert by_dimension["appday"]["used_pct"] == 0.03

    # No query strings or account/order identifiers in durable rows.
    with dashboard.connect(db_path) as db:
        rows = db.execute("SELECT endpoint,quota_json FROM pg_saxo_rest_usage_windows_v1").fetchall()
    persisted = json.dumps([dict(row) for row in rows])
    assert "very-private" not in persisted
    assert "never-save" not in persisted
    assert "AccountKey" not in persisted


def test_absent_or_incomplete_headers_do_not_invent_quota_percentage(tmp_path):
    db_path = tmp_path / "missing-headers.db"
    assert dashboard.load_saxo_rest_usage_v1(db_path=db_path) == ()
    telemetry.record_saxo_http_v1(
        "GET", "port/v1/netpositions?ClientKey=private", 200,
        headers={"X-RateLimit-Session-Remaining": "12"}, now=161.0,
    )
    assert dashboard.flush_saxo_rest_usage_v1(db_path=db_path) == 1
    stats = dashboard.summarize_saxo_rest_usage_v1(
        dashboard.load_saxo_rest_usage_v1(db_path=db_path),
    )
    assert stats["calls"] == 1
    assert stats["quotas"] == ()


def test_origin_counts_split_same_endpoint_and_persist_privately(tmp_path):
    db_path=tmp_path/"attribution.sqlite"
    telemetry.record_saxo_http_v1(
        "GET","port/v1/accounts/me?AccountKey=secret",200,
        source_module="autotrader_v3_live_saxo_v1",now=101,
    )
    telemetry.record_saxo_http_v1(
        "GET","port/v1/accounts/me?AccountKey=secret",200,
        source_module="telegram_multi_worker",now=110,
    )
    telemetry.record_saxo_http_v1(
        "GET","port/v1/accounts/me?AccountKey=secret",429,
        source_module="autotrader_v3_live_saxo_v1",now=161,
    )
    assert dashboard.flush_saxo_rest_usage_v1(db_path=db_path)==1
    aggregate=dashboard.summarize_saxo_rest_usage_v1(
        dashboard.load_saxo_rest_usage_v1(db_path=db_path))
    origin=dashboard.summarize_saxo_rest_call_origins_v1(
        dashboard.load_saxo_rest_call_origins_v1(db_path=db_path))
    assert aggregate['calls']==3
    assert origin['total']==3
    assert origin['sources']==(
        {'source_module':'autotrader_v3_live_saxo_v1','calls':2,'http429':1},
        {'source_module':'telegram_multi_worker','calls':1,'http429':0},
    )
    assert origin['routes'][0]['endpoint']=='port/v1/accounts'
    with dashboard.connect(db_path) as db:
        saved=str([dict(row) for row in db.execute(
            'SELECT * FROM pg_saxo_rest_call_origins_v1').fetchall()])
    assert 'secret' not in saved
    assert 'AccountKey' not in saved


def test_origin_module_identifier_is_sanitized_and_unknown_stays_visible():
    telemetry.record_saxo_http_v1(
        "GET","port/v1/netpositions",200,
        source_module="unsafe?AccountKey=secret",now=161,
    )
    rows=telemetry.drain_saxo_rest_usage_v1()
    assert rows[0]['origins']==(
        {'source_module':'unknown','call_count':1,'http429_count':0},)


def test_failed_persistence_restores_buffer_for_retry(tmp_path, monkeypatch):
    telemetry.record_saxo_http_v1("GET", "port/v1/accounts", 429, now=161.0)
    real_ensure = dashboard.ensure_saxo_rest_usage_schema_v1

    def fail(_db_path):
        raise ConnectionError("database unavailable")

    monkeypatch.setattr(dashboard, "ensure_saxo_rest_usage_schema_v1", fail)
    with pytest.raises(ConnectionError, match="database unavailable"):
        dashboard.flush_saxo_rest_usage_v1(db_path=tmp_path / "retry.db")
    assert len(telemetry._OUTBOX) == 1
    monkeypatch.setattr(dashboard, "ensure_saxo_rest_usage_schema_v1", real_ensure)
    assert dashboard.flush_saxo_rest_usage_v1(db_path=tmp_path / "retry.db") == 1
    assert len(telemetry._OUTBOX) == 0


def test_invalid_quota_headers_never_display_false_or_negative_usage():
    telemetry.record_saxo_http_v1(
        "GET", "port/v1/netpositions", 200, now=161.0,
        headers={
            "X-RateLimit-Session-Limit": "0",
            "X-RateLimit-Session-Remaining": "1000000000000000",
            "X-RateLimit-Session-Reset": "-1",
        },
    )
    stats = dashboard.summarize_saxo_rest_usage_v1(telemetry.drain_saxo_rest_usage_v1())
    assert stats["quotas"] == ()


def test_quota_sample_is_read_only_and_latest_completed_window_wins():
    newer = {
        "window_ended_at": "2026-11-19T12:01:00+00:00", "method": "GET",
        "endpoint": "port/v1/accounts", "call_count": 10, "http429_count": 0,
        "quota": {"session": {"limit": 120, "remaining": 60, "reset": 20}},
    }
    older = {**newer, "window_ended_at": "2026-11-19T12:00:00+00:00",
             "quota": {"session": {"limit": 120, "remaining": 110, "reset": 50}}}
    stats = dashboard.summarize_saxo_rest_usage_v1([newer, older])
    assert stats["calls"] == 20
    assert stats["quotas"][0]["used_pct"] == 50.0
    assert stats["quotas"][0]["reset_seconds"] == 20
