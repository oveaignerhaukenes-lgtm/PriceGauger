"""Prospective and isolated context ablation against five frozen lab parents."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from database import connect
from macro_calendar import MacroEvent
from live_sim_lab_store_v1 import ensure_lab_schema, seed_default_experiments
from live_sim_lab_context_ablation_v1 import (
    ARM_NAMES, COHORT_SIZE, _calendar_risk, _geopolitical_risk,
    _cap_target, context_ablation_snapshot, context_for_bar,
    ensure_context_lab_schema, freeze_five_candidates,
    refresh_macro_schedule, settle_context_ablations,
)

BASE=datetime(2026,10,12,13,0,tzinfo=timezone.utc)


def stamp(offset=0):
    return (BASE+timedelta(minutes=offset)).isoformat()


def make_db(tmp_path):
    path=str(tmp_path/"sim.db")
    ensure_lab_schema(path)
    with connect(path) as db:
        ensure_context_lab_schema(db)
        db.execute("""CREATE TABLE context_v2_snapshots(
            snapshot_id TEXT PRIMARY KEY,scope_key TEXT,as_of TEXT,recorded_at TEXT,
            payload_json TEXT
        )""")
        seed_default_experiments(db,instrument_id=4912,
                                 market_name="US Tech 100 NAS",now=stamp(-500))
    return path


def make_event(at=stamp(10)):
    return MacroEvent(event_id="US_CPI:"+at,scheduled_at=datetime.fromisoformat(at),
                      title="US CPI",source="BLS",source_url="https://www.bls.gov/cpi/",
                      importance="HIGH",markets=("DXY",),event_type="US_CPI")


def available_parent(equity=10200):
    samples=[[stamp(-130+5*i),10000+(equity-10000)*i/24] for i in range(25)]
    return {"equity":equity,"peak":equity,"exposure":1.0,"pending":1.0,
            "trades":5,"max_drawdown":0.01,
            "_evo":{"bars":135,"samples":samples,"regime_stats":{}}}


def test_macro_provenance_never_backfills_events(tmp_path):
    path=make_db(tmp_path)
    report=refresh_macro_schedule(db_path=path,now=BASE,
                                  loader=lambda **_:
                                  SimpleNamespace(events=(make_event(),),source_errors=()))
    assert report=="READY"
    with connect(path) as db:
        assert _calendar_risk(db,bar_time=stamp(-1))["status"]=="MISSING"
        a=_calendar_risk(db,bar_time=stamp(0))
        assert a["risk"] and a["event_id"].startswith("US_CPI:")
        assert not _calendar_risk(db,bar_time=stamp(60))["risk"]
    # A second call before the refresh horizon must not fetch anything.
    def explode(**_):
        raise AssertionError("unexpected network refresh")
    assert refresh_macro_schedule(db_path=path,now=BASE+timedelta(hours=2),
                                  loader=explode)=="UNCHANGED"


def test_macro_event_known_only_after_recording_and_explicit_missing(tmp_path):
    path=make_db(tmp_path)
    with connect(path) as db:
        db.execute("""INSERT INTO lsim_ctx_macro_refresh
            VALUES(1,?,'READY','[]')""",(stamp(-10),))
        db.execute("""INSERT INTO lsim_ctx_macro_events
            VALUES(?,?,?,?,?,?,?)""",(
                "FOMC",stamp(3),stamp(2),"FOMC_DECISION","CRITICAL","Fed","https://www.federalreserve.gov"))
        assert _calendar_risk(db,bar_time=stamp(0))["risk"] is False
        assert _calendar_risk(db,bar_time=stamp(2))["risk"] is True


def test_geo_context_requires_fresh_publish_and_no_future_evidence(tmp_path):
    path=make_db(tmp_path)
    def insert(db,ident,asof,recorded,evidence):
        payload={
            "freshness_status":"FRESH","coverage_end":asof,
            "evidence":evidence,"targets":[{
                "target_key":"Gold","event_risk":0.92,"confidence":0.95,
                "dimensions":[{"name":"confirmation_quality","value":0.95,
                               "confidence":0.95}]}]}
        db.execute("""INSERT INTO context_v2_snapshots VALUES(?,?,?,?,?)""",
                   (ident,"global",asof,recorded,json.dumps(payload)))
    with connect(path) as db:
        insert(db,"one",stamp(-5),stamp(-4),[])
        assert _geopolitical_risk(db,bar_time=stamp(0))["risk"] is True
        assert _geopolitical_risk(db,bar_time=stamp(-6))["status"]=="MISSING"
        insert(db,"future",stamp(-1),stamp(3),[])
        assert _geopolitical_risk(db,bar_time=stamp(0))["snapshot_id"]=="one"
        assert _geopolitical_risk(db,bar_time=stamp(30))["status"]=="MISSING"
        insert(db,"late",stamp(1),stamp(2),
               [{"observed_at":stamp(10),"published_at":stamp(10)}])
        assert _geopolitical_risk(db,bar_time=stamp(3))["snapshot_id"]=="future"


def test_five_paired_candidates_are_frozen_and_paper_only(tmp_path):
    path=make_db(tmp_path)
    with connect(path) as db:
        keys=[r["experiment_id"] for r in db.execute("""
            SELECT experiment_id FROM lsim_experiments ORDER BY experiment_id LIMIT 9
        """).fetchall()]
        candidates={key:available_parent(10010+100*i)
                    for i,key in enumerate(keys)}
        chosen=freeze_five_candidates(db,instrument_id=4912,states=candidates,
                                      bar_time=stamp())
        assert len(chosen)==COHORT_SIZE
        assert chosen==[k for _,k in sorted(
            ((10010+100*i,k) for i,k in enumerate(keys)),reverse=True)][:5]
        # Repeated selection cannot change ranking even if scores change later.
        assert sorted(freeze_five_candidates(
            db,instrument_id=4912,states={keys[0]:available_parent(13000)},
            bar_time=stamp(1)))==sorted(chosen)
        # Cohort starts at the end of the selection bar, not that bar's open.
        assert settle_context_ablations(db,instrument_id=4912,states=candidates,
              bar_time=stamp(),open_price=100,close_price=100)==0
        db.execute("""INSERT INTO lsim_ctx_macro_refresh
            VALUES(1,?,'READY','[]')""",(stamp(),))
        db.execute("""INSERT INTO lsim_ctx_macro_events VALUES(?,?,?,?,?,?,?)""",
                   ("CPI",stamp(4),stamp(),"US_CPI","HIGH","BLS","https://www.bls.gov"))
        # Following close makes policy decision; still zero exposure.
        assert settle_context_ablations(db,instrument_id=4912,states=candidates,
            bar_time=stamp(1),open_price=100,close_price=100)==20
        assert settle_context_ablations(db,instrument_id=4912,states=candidates,
            bar_time=stamp(2),open_price=100,close_price=101)==20
        assert settle_context_ablations(db,instrument_id=4912,states=candidates,
            bar_time=stamp(2),open_price=100,close_price=101)==0
        rows=db.execute("""SELECT arm,state_json FROM lsim_ctx_arms
                           WHERE experiment_id=? ORDER BY arm""",(chosen[0],)).fetchall()
        by_arm={r["arm"]:json.loads(r["state_json"]) for r in rows}
        assert set(by_arm)==set(ARM_NAMES)
        # BASE enters, macro-risk arms stayed flat from previous close.
        assert by_arm["BASE"]["equity"]>10000
        assert by_arm["MACRO"]["equity"]==10000
        assert by_arm["BOTH"]["equity"]==10000
        assert by_arm["GEO"]["equity"]==by_arm["BASE"]["equity"]
        assert by_arm["BASE"]["trades"]==1
        assert by_arm["MACRO"]["trades"]==0
        assert db.execute("SELECT COUNT(*) AS n FROM lsim_experiments WHERE status='ACTIVE'").fetchone()["n"]==72
    cohort,arms,macro,points=context_ablation_snapshot(db_path=path)
    assert len(cohort)==5 and len(arms)==20
    assert macro["status"]=="READY"


def test_context_missing_is_noop_with_visibility():
    evidence={"macro":{"status":"MISSING","risk":False},
              "geo":{"status":"MISSING","risk":False}}
    assert all(_cap_target(-0.75,kind,evidence)==-0.75 for kind in ARM_NAMES)
    evidence["geo"]["risk"]=True
    assert _cap_target(-0.75,"GEO",evidence)==-0.375
    assert _cap_target(-0.75,"MACRO",evidence)==-0.75
    evidence["macro"]["risk"]=True
    assert _cap_target(0.75,"MACRO",evidence)==0.0
    assert _cap_target(-0.75,"BOTH",evidence)==0.0


def test_context_lab_never_has_execution_imports():
    src=Path("live_sim_lab_context_ablation_v1.py").read_text()
    assert "from saxo_trading import" not in src
    assert "place_order(" not in src
    assert "run_v3_live_cycle" not in src
