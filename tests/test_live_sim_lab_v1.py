from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from database import connect
from live_sim_lab_core_v1 import (
    advance_features, experiment_decision, initial_features, settle_bar,
    technical_regime,
)
from live_sim_lab_store_v1 import (
    MAX_ACTIVE_LAB_VARIANTS, candidate_configs, ensure_lab_schema,
    lab_snapshot, process_lab_cycle, seed_default_experiments,
)


def _dt(index):
    return datetime(2026, 10, 8, tzinfo=timezone.utc) + timedelta(minutes=index)


def _config(modifier="none"):
    return dict(family="sticky", signal_tf=2, regime_tf=10,
                modifier=modifier, max_exposure=1.0, cost_bps=5.0)


def test_shared_features_are_incremental_and_reject_duplicate_bars():
    state = initial_features()
    for i in range(70):
        state = advance_features(state, bar_time=_dt(i), close=100 + i * 0.02)
    assert state["macd"]["2"]["closed_count"] == 35
    assert state["macd"]["10"]["closed_count"] == 7
    assert len(state["returns"]) == 69
    with pytest.raises(ValueError, match="strictly increasing"):
        advance_features(state, bar_time=_dt(69), close=123)


def test_normalized_paper_fill_only_on_next_bar_and_turnover_cost():
    state = {"equity":10000.0, "peak":10000.0, "exposure":0.0,
             "last_close":100.0, "pending":1.0, "trades":0}
    features = initial_features()
    next_state, outcome = settle_bar(_config(), state, features,
                                     bar_time=_dt(0), open_price=100,
                                     close_price=100)
    assert outcome["trade"] is True
    assert next_state["equity"] == pytest.approx(9995.0)
    assert next_state["trades"] == 1
    assert next_state["exposure"] == 1.0
    newer, outcome2 = settle_bar(_config(), next_state, features,
                                  bar_time=_dt(1), open_price=101,
                                  close_price=102)
    assert outcome2["trade"] is False
    assert newer["equity"] == pytest.approx(9995.0 * 1.02)


def test_regime_needs_observations_then_classifies_from_known_only():
    assert technical_regime([0.001] * 29) == ("WARMUP", [])
    label, tags = technical_regime([0.001] * 45)
    assert label in ("TREND","IMPULSE")
    assert isinstance(tags, list)


def test_decision_does_not_trade_without_closed_signal_bar_or_indicators():
    cfg = _config()
    assert experiment_decision(cfg, {}, initial_features(), bar_time=_dt(0))[0] is None
    assert experiment_decision(cfg, {}, initial_features(), bar_time=_dt(1))[0] is None


def test_exact_72_default_variants_and_hard_cap(tmp_path):
    assert len(list(candidate_configs())) == 72
    assert MAX_ACTIVE_LAB_VARIANTS == 100
    path = str(tmp_path / "lab.sqlite")
    ensure_lab_schema(path)
    with connect(path) as db:
        assert seed_default_experiments(
            db,instrument_id=17,market_name="US Tech 100 NAS",
            now=_dt(0).isoformat()) == 72
        assert seed_default_experiments(
            db,instrument_id=17,market_name="US Tech 100 NAS",
            now=_dt(1).isoformat()) == 0
        count = db.execute("SELECT COUNT(*) AS n FROM lsim_experiments").fetchone()["n"]
        assert count == 72


def test_bootstrap_never_books_historical_profits_and_future_only(tmp_path):
    path = str(tmp_path / "market.sqlite")
    with connect(path) as db:
        db.executescript("""
        CREATE TABLE pg_v2_markets(market_id INTEGER PRIMARY KEY,name TEXT,active BOOLEAN);
        CREATE TABLE pg_v2_instruments(instrument_id INTEGER PRIMARY KEY,market_id INTEGER,active BOOLEAN);
        CREATE TABLE pg_v2_collection_subscriptions(instrument_id INTEGER,enabled BOOLEAN);
        CREATE TABLE pg_v2_market_bars_1m(
            instrument_id INTEGER,bar_time TEXT,open REAL,high REAL,low REAL,close REAL
        );
        """)
        db.execute("INSERT INTO pg_v2_markets VALUES(1,'US Tech 100 NAS',1)")
        db.execute("INSERT INTO pg_v2_instruments VALUES(17,1,1)")
        db.execute("INSERT INTO pg_v2_collection_subscriptions VALUES(17,1)")
        for i in range(1120):
            value = 100.0 + 0.01 * i
            db.execute("INSERT INTO pg_v2_market_bars_1m VALUES(?,?,?,?,?,?)",
                       (17,_dt(i).isoformat(),value,value,value,value))
    # Start long after warmup closes. No historical equity/trades may be claimed.
    at = _dt(1125)
    assert process_lab_cycle(db_path=path,now=at) == 0
    variants, memory, feeds = lab_snapshot(db_path=path)
    assert len(variants) == 72 and len(feeds) == 1
    assert not memory
    assert all(v["trades"] == 0 and v["equity"] == 10000 for v in variants)
    # Add one new closed 1m bar. Only this genuinely subsequent bar is scored.
    with connect(path) as db:
        db.execute("INSERT INTO pg_v2_market_bars_1m VALUES(?,?,?,?,?,?)",
                   (17,_dt(1126).isoformat(),111.26,111.26,111.26,111.26))
    assert process_lab_cycle(db_path=path,now=_dt(1128)) == 1
    variants, memory, _ = lab_snapshot(db_path=path)
    assert len(memory) == 72
    assert all(v["last_bar"] == _dt(1126).isoformat() for v in variants)
    # Idempotent rerun cannot double-charge, double-count, or double-score.
    assert process_lab_cycle(db_path=path,now=_dt(1128)) == 0
    _, again, _ = lab_snapshot(db_path=path)
    assert memory == again


def test_independent_worker_has_no_broker_mutation_imports():
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    for name in ("live_sim_lab_core_v1.py",
                 "live_sim_lab_store_v1.py","live_sim_lab_worker_v1.py"):
        data = (root / name).read_text()
        assert "from saxo_trading import" not in data
        assert "place_order(" not in data
        assert "run_v3_live_cycle_v1" not in data


def test_ui_is_registered_as_separate_menu_item():
    from navigation_config import PAGE_GROUPS
    pages = [entry for page_group in PAGE_GROUPS.values() for entry in page_group]
    assert any(p["title"]=="Live-Sim Lab"
               and p["page"]=="pages/0_Live_Sim_Lab.py" for p in pages)
