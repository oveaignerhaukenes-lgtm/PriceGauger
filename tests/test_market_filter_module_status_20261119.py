"""Module map is an honest, read-only view of observed V3 evidence."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from database import connect
from market_filter_module_status_v1 import (
    MODULES_V1, evidence_freshness_v1, latest_observed_timestamp_v1,
    load_market_filter_evidence_v1,
)
from navigation_config import PAGE_GROUPS


NOW = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)


def _at(minutes):
    return (NOW - timedelta(minutes=minutes)).isoformat()


def test_freshness_never_calls_missing_or_stale_data_a_broken_saxo_link():
    assert evidence_freshness_v1(None, now=NOW)["label"] == "INGEN OBSERVASJON"
    assert evidence_freshness_v1(_at(1), now=NOW)["label"] == "NYLIGE DATA"
    status = evidence_freshness_v1(_at(10), now=NOW)
    assert status["symbol"] == "🟠"
    assert status["label"] == "INGEN NYE DATA"
    assert status["age_seconds"] == 600
    assert evidence_freshness_v1(_at(-5), now=NOW)["label"] == "KLOKKEAVVIK"
    assert evidence_freshness_v1("2026-11-19T12:00:00", now=NOW)["symbol"] == "⚪"
    assert evidence_freshness_v1("2026-11-19 11:59:00",now=NOW,
                                 sql_utc=True)["label"] == "NYLIGE DATA"
    assert latest_observed_timestamp_v1((None,_at(2),NOW-timedelta(minutes=1))) == (
        NOW-timedelta(minutes=1))


def test_no_producer_tables_is_unknown_not_zero_confirmed_performance(tmp_path):
    view = load_market_filter_evidence_v1(
        instance_ids=("instA",), instrument_ids=(4912,), account_ids=("acct" ,),
        db_path=tmp_path / "new.db", now=NOW,
    )
    assert not view["observer_table_present"]
    assert not view["rest_table_present"]
    assert not view["stream_table_present"]
    assert view["total"] == 0
    assert view["matured"] == 0
    assert view["bars"] == {}
    assert view["instances"] == {}


def test_stats_follow_exact_sources_and_only_matured_future_candles(tmp_path):
    db_path = tmp_path / "evidence.db"
    with connect(db_path) as db:
        db.execute("""CREATE TABLE pg_v3_state_strategy_observations_v1 (
            instance_id TEXT, account_id TEXT, observed_as_of TEXT,
            strategy_key TEXT, state_key TEXT,
            future_5m_completed_at TEXT, future_5m_price_return_pct REAL,
            efficiency REAL,direction_changes INTEGER,
            volatility_pct_1m REAL,rhythm_evidence TEXT)""")
        db.execute("""CREATE TABLE pg_v2_market_bars_1m (
            instrument_id INTEGER,bar_time TEXT)""")
        db.execute("""CREATE TABLE autotrader_v3_live_runtime_state (
            trader_id TEXT,status TEXT,updated_at TEXT)""")
        db.execute("""CREATE TABLE pg_saxo_account_truth_v1 (
            account_id TEXT,account_name TEXT,observed_at TEXT)""")
        db.execute("""CREATE TABLE pg_saxo_rest_usage_windows_v1 (
            window_ended_at TEXT,call_count INTEGER)""")
        db.execute("""CREATE TABLE realtime_stream_status (
            market TEXT,updated_at TEXT,state TEXT)""")
        for minutes,matured,change in ((5,True,-0.4),(10,False,None),(13,True,0.2)):
            db.execute("""INSERT INTO pg_v3_state_strategy_observations_v1
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""", (
                "instA","acctA",_at(minutes),"impulse-catcher-long-v1", "UP/FAST",
                _at(minutes-5) if matured else None,change,0.8,2,0.12,"WEAK",
            ))
        # Outside requested interval, must never leak into the statistics.
        db.execute("""INSERT INTO pg_v3_state_strategy_observations_v1
            VALUES (?,?,?,?,?,?,?,?,?,?,?)""", (
            "instB","acctB",_at(25*60),"old-model","DOWN/SLOW",None,None,
            0.4,5,0.2,"WEAK"))
        for inst,minutes in ((4912,2),(4913,120)):
            db.execute("INSERT INTO pg_v2_market_bars_1m VALUES (?,?)", (inst,_at(minutes)))
        db.execute("INSERT INTO autotrader_v3_live_runtime_state VALUES (?,?,?)",
                   ("instA", "READY", _at(1)))
        db.execute("INSERT INTO pg_saxo_account_truth_v1 VALUES (?,?,?)",
                   ("acctA", "Tech100-E", _at(5)))
        db.execute("INSERT INTO pg_saxo_account_truth_v1 VALUES (?,?,?)",
                   ("acctA", "Tech100-E - gammel", _at(10)))
        db.execute("INSERT INTO pg_saxo_rest_usage_windows_v1 VALUES (?,?)",
                   (_at(1),40))
        db.execute("INSERT INTO pg_saxo_rest_usage_windows_v1 VALUES (?,?)",
                   (_at(17),200))
        db.execute("INSERT INTO realtime_stream_status VALUES (?,?,?)",
                   ("US Tech 100 NAS",_at(1),"STREAMING"))

    view = load_market_filter_evidence_v1(
        instance_ids=("instA",), instrument_ids=(4912,), account_ids=("acctA",),
        hours=24,db_path=db_path,now=NOW,
    )
    assert view["observer_table_present"]
    assert view["total"] == 3
    assert view["matured"] == 2
    assert view["last_observed"] == _at(5)
    assert view["instances"]["instA"]["matured"] == 2
    assert view["latest_profiles"]["instA"]["state_key"] == "UP/FAST"
    assert view["latest_profiles"]["instA"]["efficiency"] == 0.8
    assert view["profiles"][0]["samples"] == 3
    assert view["profiles"][0]["mean_future_price_pct"] == pytest.approx(-0.1)
    assert view["bars"] == {4912:_at(2)}
    assert view["runtime"]["instA"]["status"] == "READY"
    assert view["account_names"]["acctA"] == "Tech100-E"
    assert view["rest_table_present"]
    assert view["rest_calls_15m"] == 40
    assert view["rest_last"] == _at(1)
    assert view["stream_table_present"]
    assert view["streams"]["US Tech 100 NAS"]["state"] == "STREAMING"
    assert view["stream_last"] == NOW-timedelta(minutes=1)


def test_catalog_is_bounded_and_every_module_has_a_real_navigation_page():
    known = {x["page"] for group in PAGE_GROUPS.values() for x in group}
    assert {module.key for module in MODULES_V1} == {
        "canonical", "profile", "observer", "impulse_bridge", "filter", "rest", "paper",
    }
    assert len({module.key for module in MODULES_V1}) == len(MODULES_V1)
    assert all(module.page in known for module in MODULES_V1)
    assert all(module.source and module.operation and module.output
               and module.settings for module in MODULES_V1)


def test_unexpected_database_errors_are_not_silently_reported_as_empty(monkeypatch):
    import market_filter_module_status_v1 as module

    def fail(*_args,**_kwargs):
        raise ConnectionError("postgres unavailable")

    monkeypatch.setattr(module,"_optional_rows",fail)
    with pytest.raises(ConnectionError):
        module.load_market_filter_evidence_v1(db_path="unused.db",now=NOW)
