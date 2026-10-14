"""Forward AEn is prospective, bounded, immutable, idempotent and broker-free."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import math

from database import connect
import aen_forward_paper_v1 as forward
from aen_replay_v1 import AEnPaperConfig, FAMILIES

START=datetime(2026,10,14,0,0,tzinfo=timezone.utc)


def setup_feed(path,*,count=655):
    with connect(path,force_sqlite=True) as db:
        db.executescript("""
            CREATE TABLE lsim_feature_cursors(
                instrument_id INTEGER PRIMARY KEY, market_name TEXT NOT NULL);
            CREATE TABLE pg_v2_market_bars_1m(
                instrument_id INTEGER NOT NULL,bar_time TEXT NOT NULL,
                open REAL NOT NULL,high REAL NOT NULL,low REAL NOT NULL,
                close REAL NOT NULL,volume REAL,
                PRIMARY KEY(instrument_id,bar_time));
        """)
        db.execute("INSERT INTO lsim_feature_cursors VALUES(101,'US Tech 100 NAS')")
        for i in range(count):
            at=(START+timedelta(minutes=i)).isoformat()
            price=100+math.sin(i/12)*.8 + i*.001
            close=price+math.sin(i/3)*.1
            db.execute("""INSERT INTO pg_v2_market_bars_1m
                VALUES(?,?,?,?,?,?,?)""",
                (101,at,price,max(price,close)+.05,min(price,close)-.05,
                 close,float(10+(i%15))))


def test_five_frozen_one_unit_paper_cohorts():
    assert len(forward.FROZEN_PRESETS)==5
    assert len({forward._run_id(101,cfg) for cfg in forward.FROZEN_PRESETS})==5
    assert all(cfg.max_units==1 and cfg.costs_enabled for cfg in forward.FROZEN_PRESETS)
    assert set(cfg.family for cfg in forward.FROZEN_PRESETS)==set(FAMILIES)


def test_forward_never_backdates_and_restart_is_idempotent(tmp_path):
    path=str(tmp_path/"forward.sqlite")
    setup_feed(path)
    launched=START+timedelta(minutes=610,seconds=10)
    assert forward.process_forward_cycle(db_path=path,now=launched)==0
    runs,points=forward.forward_snapshot(db_path=path,instrument_id=101)
    assert len(runs)==5
    assert all(r["last_bar_end"] is None for r in runs)
    assert not points
    enrolled=START+timedelta(minutes=611)
    assert all(forward.utc(r["enrolled_at"])==enrolled for r in runs)
    # Historical candles for the first ten hours exist but MUST yield 0%
    # prospective results until a NEW candle closes after enrolment.
    assert all(float(r["net_pct"])==0 for r in runs)
    moment=START+timedelta(minutes=621,seconds=10)
    assert forward.process_forward_cycle(db_path=path,now=moment)==5
    runs,points=forward.forward_snapshot(db_path=path,instrument_id=101)
    assert all(r["last_bar_end"] and forward.utc(r["last_bar_end"])>enrolled for r in runs)
    assert all(forward.utc(p["bar_end"])>enrolled for p in points)
    assert all(abs(r["units"])<=1 for r in runs)
    assert len(points)>0
    assert forward.process_forward_cycle(db_path=path,now=moment)==0
    assert forward.forward_snapshot(db_path=path,instrument_id=101)==(runs,points)
    with connect(path,force_sqlite=True) as db:
        count=db.execute("SELECT COUNT(*) AS n FROM aen_forward_runs").fetchone()["n"]
        assert count==5
        assert db.execute("SELECT COUNT(*) AS n FROM aen_forward_points").fetchone()["n"]==len(points)


def test_causal_cutoff_ignores_future_db_rows(tmp_path):
    path=str(tmp_path/"forward.sqlite")
    setup_feed(path)
    t=START+timedelta(minutes=610,seconds=10)
    forward.process_forward_cycle(db_path=path,now=t)
    second=START+timedelta(minutes=617,seconds=10)
    forward.process_forward_cycle(db_path=path,now=second)
    runs,_=forward.forward_snapshot(db_path=path,instrument_id=101)
    # At 10:17:10, latest eligible open is 10:16, end at 10:17.
    assert all(forward.utc(r["last_bar_end"])<=second-timedelta(seconds=5)
               for r in runs if r["last_bar_end"])


def test_revised_past_is_paused_not_silently_rewritten(tmp_path,monkeypatch):
    path=str(tmp_path/"forward.sqlite")
    setup_feed(path)
    forward.process_forward_cycle(db_path=path,now=START+timedelta(minutes=610))
    forward.process_forward_cycle(db_path=path,now=START+timedelta(minutes=621))
    old,_=forward.forward_snapshot(db_path=path,instrument_id=101)
    real=forward.replay
    def modified(*args,**kwargs):
        report=real(*args,**kwargs)
        changed=tuple((t,p+.1,g,units) for t,p,g,units in report.points)
        return replace(report,points=changed,return_pct=report.return_pct+.1)
    monkeypatch.setattr(forward,"replay",modified)
    forward.process_forward_cycle(db_path=path,now=START+timedelta(minutes=625))
    current,_=forward.forward_snapshot(db_path=path,instrument_id=101)
    assert all(r["status"]=="PAUSED_REVISION" for r in current)
    assert {r["run_id"]:r["last_bar_end"] for r in current} == {
           r["run_id"]:r["last_bar_end"] for r in old}



def test_revision_is_detected_even_if_strategy_was_flat(tmp_path):
    path=str(tmp_path/"forward.sqlite")
    setup_feed(path)
    forward.process_forward_cycle(db_path=path,now=START+timedelta(minutes=610))
    forward.process_forward_cycle(db_path=path,now=START+timedelta(minutes=621))
    before,_=forward.forward_snapshot(db_path=path,instrument_id=101)
    assert all(r["prefix_sha"] for r in before)
    # Modify a completed input candle in the immutable observation prefix.
    # A P/L-only comparator could miss this when all variants are flat.
    with connect(path,force_sqlite=True) as db:
        db.execute("""
            UPDATE pg_v2_market_bars_1m SET high=high+0.0001
            WHERE instrument_id=? AND bar_time=?
        """,(101,(START+timedelta(minutes=606)).isoformat()))
    forward.process_forward_cycle(db_path=path,now=START+timedelta(minutes=626))
    current,_=forward.forward_snapshot(db_path=path,instrument_id=101)
    assert all(r["status"]=="PAUSED_REVISION" for r in current)
    assert {r["run_id"]:r["last_bar_end"] for r in current}=={
           r["run_id"]:r["last_bar_end"] for r in before}


def test_expired_cohorts_stop_without_deleting_history(tmp_path):
    path=str(tmp_path/"forward.sqlite")
    setup_feed(path)
    forward.process_forward_cycle(db_path=path,now=START+timedelta(minutes=610))
    later=START+timedelta(days=16)
    forward.process_forward_cycle(db_path=path,now=later)
    runs,_=forward.forward_snapshot(db_path=path,instrument_id=101)
    assert all(r["status"]=="COMPLETED" for r in runs)
    assert len(runs)==5



def test_short_prehistory_stays_active_and_warms_up_causally(tmp_path):
    """A sparse feed may start a valid forward cohort without 8h of history."""
    path=str(tmp_path/"short.sqlite")
    setup_feed(path,count=160)
    launched=START+timedelta(minutes=70,seconds=10)
    assert forward.process_forward_cycle(db_path=path,now=launched)==0
    # New observations are after future enrolment, not retrofitted returns.
    moment=START+timedelta(minutes=105,seconds=10)
    assert forward.process_forward_cycle(db_path=path,now=moment)==5
    runs,points=forward.forward_snapshot(db_path=path,instrument_id=101)
    assert len(runs)==5
    assert all(r["status"]=="ACTIVE" for r in runs)
    assert all(forward.utc(r["last_bar_end"])>
               forward.utc(r["enrolled_at"]) for r in runs)
    assert all(forward.utc(p["bar_end"])>
               forward.utc(next(r["enrolled_at"] for r in runs
                                if r["run_id"]==p["run_id"])) for p in points)
    # Old releases paused never-started runs with no fills: resume without
    # touching original start or any actual performance evidence.
    with connect(path,force_sqlite=True) as db:
        db.execute("UPDATE aen_forward_runs SET status='PAUSED_HISTORY',last_bar_end=NULL,"
                   "net_pct=0,gross_pct=0 WHERE instrument_id=101")
        db.execute("DELETE FROM aen_forward_points WHERE 1=1")
    assert forward.process_forward_cycle(db_path=path,
                   now=START+timedelta(minutes=120,seconds=10))==5
    resumed,_=forward.forward_snapshot(db_path=path,instrument_id=101)
    assert all(r["status"]=="ACTIVE" for r in resumed)
    assert {r["run_id"]:r["enrolled_at"] for r in resumed}=={
           r["run_id"]:r["enrolled_at"] for r in runs}


def test_missing_lab_feed_does_not_seed_fictitious_market(tmp_path):
    path=str(tmp_path/"empty.sqlite")
    assert forward.process_forward_cycle(db_path=path,now=START)==0
    runs,points=forward.forward_snapshot(db_path=path)
    assert (runs,points)==([],[])




def test_eligible_markets_no_literal_sql_percent_and_filter_in_python():
    """A Postgres-like adapter rejects unsafe percent format tokens."""
    class StrictAdapter:
        def execute(self,sql):
            assert "%" not in sql  # literal LIKE patterns break some DB adapters
            assert "ORDER BY instrument_id" in sql
            return self

        def fetchall(self):
            return [
                {"instrument_id":2,"market_name":"WisdomTree Gold"},
                {"instrument_id":7,"market_name":"US Tech 100 NAS · Saxo 4912"},
                {"instrument_id":8,"market_name":"Other tech"},
            ]
    assert forward._eligible(StrictAdapter())==[
        (7,"US Tech 100 NAS · Saxo 4912")
    ]


def test_cohort_health_read_only_and_bounded(tmp_path):
    path=str(tmp_path/"health.sqlite")
    setup_feed(path,count=690)
    forward.ensure_schema(path)
    initial=forward.forward_health_snapshot(db_path=path)
    assert initial["feeds"]==1
    assert initial["cohorts"]==[]
    # A health read must NEVER enrol a new cohort.
    again=forward.forward_health_snapshot(db_path=path)
    assert again==initial
    forward.process_forward_cycle(db_path=path,
        now=START+timedelta(minutes=610,seconds=11))
    after=forward.forward_health_snapshot(db_path=path)
    assert after["feeds"]==1
    assert sum(row["count"] for row in after["cohorts"])==5
    assert {row["status"] for row in after["cohorts"]}=={"ACTIVE"}
    assert all("config_json" not in row for row in after["cohorts"])
    worker=Path("live_sim_lab_worker_v1.py").read_text()
    assert "AEN_FORWARD_HEALTH" in worker
    assert "timedelta(minutes=5)" in worker


def test_no_order_broker_or_live_authority_code():
    source=Path("aen_forward_paper_v1.py").read_text()
    for banned in ("from saxo", "place_order(", "configured_client",
                   "live_authority_armed", "set_live_enabled"):
        assert banned not in source
    worker=Path("live_sim_lab_worker_v1.py").read_text()
    assert "from aen_forward_paper_v1 import process_forward_cycle" in worker
    ui=Path("aen_lab_ui_v1.py").read_text()
    assert "render_aen_forward_panel_v1" in ui
    assert "forward_snapshot" in ui
