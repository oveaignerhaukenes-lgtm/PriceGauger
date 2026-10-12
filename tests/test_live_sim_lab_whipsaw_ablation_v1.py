"""Causal, paired Whipsaw Lab regression tests. No V3 LIVE authority."""
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path

import pytest

from database import connect
from live_sim_lab_store_v1 import ensure_lab_schema,seed_default_experiments
from live_sim_lab_whipsaw_ablation_v1 import (
    ARMS, _initial_track, _updated_detector, detector_evidence,
    ensure_whipsaw_schema, freeze_whipsaw_cohort, select_policy_target,
    settle_whipsaw_ablation, whipsaw_snapshot,
)

START=datetime(2026,10,12,14,0,tzinfo=timezone.utc)


def stamp(n):
    return (START+timedelta(minutes=n)).isoformat()


def db_path(tmp_path):
    path=str(tmp_path/"lab.db")
    ensure_lab_schema(path)
    with connect(path) as db:
        ensure_whipsaw_schema(db)
        seed_default_experiments(db,instrument_id=4912,
                                 market_name="Tech100",now=stamp(-600))
    return path


def state(value=10090,pending=1):
    samples=[[stamp(-150+i*5),10000+(value-10000)*i/24] for i in range(25)]
    return {
        "equity":value,"peak":value,"exposure":pending,"pending":pending,
        "max_drawdown":0.02,"trades":8,
        "_evo":{"bars":150,"samples":samples},
    }


def parents(db):
    rows=db.execute(
        "SELECT experiment_id,config_json FROM lsim_experiments ORDER BY experiment_id"
    ).fetchall()
    ids=[r["experiment_id"] for r in rows
         if json.loads(r["config_json"])["modifier"]=="none"]
    return {key:state(10020+i*25) for i,key in enumerate(ids[:7])}


def test_detector_is_existing_closed_bar_whipsaw_not_a_new_classifier():
    moves=[0.001,-0.001]*6
    evidence=detector_evidence({"returns":moves,"tags":["WHIPSAW"]})
    assert evidence["raw"] is True
    assert evidence["changes"]==11
    assert evidence["efficiency"]==0
    assert detector_evidence({"returns":[0.001]*12,"tags":["TREND"]})["raw"] is False
    assert detector_evidence({"returns":[0.001]*4,"tags":[]})["changes"] is None


def test_hysteresis_does_not_release_after_one_quiet_bar():
    s=_initial_track()
    assert _updated_detector(s,raw=True)
    assert s["activation_count"]==1
    assert s["cooldown_remaining"]==3
    assert _updated_detector(s,raw=False)
    assert _updated_detector(s,raw=False)
    assert not _updated_detector(s,raw=False)
    assert s["activation_count"]==1
    assert not s["active"]
    assert s["cooldown_remaining"]==0
    assert _updated_detector(s,raw=True)
    assert s["activation_count"]==2


@pytest.mark.parametrize("base,current,policy,expected",[
    (1.0,0.0,"BASE",1.0),
    (1.0,0.0,"PAUSE",0.0),
    (1.0,0.5,"PAUSE",0.5),
    (0.0,1.0,"PAUSE",0.0),
    (-1.0,1.0,"PAUSE",0.0),
    (1.0,0.0,"REDUCE",0.0),
    (1.0,1.0,"REDUCE",0.5),
    (0.3,1.0,"REDUCE",0.3),
    (0.0,1.0,"REDUCE",0.0),
    (-1.0,1.0,"REDUCE",0.0),
    (1.0,1.0,"FLAT",0.0),
    (0.0,0.0,"FLAT",0.0),
])
def test_each_policy_exact_semantics(base,current,policy,expected):
    result,_=select_policy_target(
        arm=policy,parent_target=base,current_exposure=current,
        config={"max_exposure":1.0},active=True,forbidden=True)
    assert result==expected


def test_normal_conditions_do_not_disturb_any_arm():
    for arm in ARMS:
        result,reason=select_policy_target(
            arm=arm,parent_target=-0.7,current_exposure=0.2,
            config={"max_exposure":1.0},active=False,forbidden=False)
        assert result==-0.7
        assert reason=="PASS"


def test_freeze_cohort_equal_start_no_reselection_and_not_backfilled(tmp_path):
    path=db_path(tmp_path)
    with connect(path) as db:
        candidates=parents(db)
        cohort=freeze_whipsaw_cohort(
            db,instrument_id=4912,parent_states=candidates,stamp=stamp(0))
        assert len(cohort)==5
        assert len(set(cohort))==5
        assert freeze_whipsaw_cohort(
            db,instrument_id=4912,parent_states={},stamp=stamp(10))==sorted(cohort)
        assert settle_whipsaw_ablation(
            db,instrument_id=4912,parent_states=candidates,
            features={"returns":[0.001,-0.001]*6,"tags":["WHIPSAW"]},
            bar_time=stamp(0),open_price=100,close_price=100)==0
        assert db.execute("SELECT COUNT(*) AS n FROM lsim_whip_tracks").fetchone()["n"]==0
        # First observed bar, policy only affects next open (not this close).
        assert settle_whipsaw_ablation(
            db,instrument_id=4912,parent_states=candidates,
            features={"returns":[0.001,-0.001]*6,"tags":["WHIPSAW"]},
            bar_time=stamp(1),open_price=100,close_price=100)==20
        assert settle_whipsaw_ablation(
            db,instrument_id=4912,parent_states=candidates,
            features={"returns":[0.001,-0.001]*6,"tags":["WHIPSAW"]},
            bar_time=stamp(2),open_price=100,close_price=101)==20
        assert settle_whipsaw_ablation(
            db,instrument_id=4912,parent_states=candidates,
            features={"returns":[0.001,-0.001]*6,"tags":["WHIPSAW"]},
            bar_time=stamp(2),open_price=100,close_price=101)==0
        rows=db.execute(
            "SELECT arm,state_json FROM lsim_whip_tracks WHERE experiment_id=?",
            (cohort[0],)).fetchall()
        tracks={x["arm"]:json.loads(x["state_json"]) for x in rows}
        assert set(tracks)==set(ARMS)
        assert tracks["BASE"]["equity"]==pytest.approx(
            10000*(1-0.0005)*1.01)
        assert tracks["PAUSE"]["equity"]==10000
        assert tracks["REDUCE"]["equity"]==10000
        assert tracks["FLAT"]["equity"]==10000
        assert tracks["BASE"]["trades"]==1
        assert tracks["FLAT"]["trades"]==0
        assert tracks["FLAT"]["activation_count"]==1
        assert tracks["REDUCE"]["blocked_increases"]>=1
        assert db.execute(
            "SELECT COUNT(*) AS n FROM lsim_experiments WHERE status='ACTIVE'"
        ).fetchone()["n"]==72
    selected,streams,_=whipsaw_snapshot(db_path=path)
    assert len(selected)==5 and len(streams)==20
    assert all(x["first_bar"]==stamp(1) for x in streams)


def test_policy_release_requires_three_clean_bars_and_flat_cooldown():
    s=_initial_track()
    _updated_detector(s,raw=True)
    for n in range(1,3):
        active=_updated_detector(s,raw=False)
        proposed,_=select_policy_target(
            arm="FLAT",parent_target=1.0,current_exposure=0,
            config={"max_exposure":1},active=s["active"],forbidden=active)
        assert proposed==0
    assert not _updated_detector(s,raw=False)
    proposed,_=select_policy_target(
        arm="FLAT",parent_target=1.0,current_exposure=0,
        config={"max_exposure":1},active=False,forbidden=False)
    assert proposed==1


def test_ablation_is_not_live_execution_or_config_mutation():
    root=Path(__file__).resolve().parent.parent
    for name in ("live_sim_lab_whipsaw_ablation_v1.py",):
        source=(root/name).read_text()
        assert "import saxo" not in source
        assert "run_v3_live_cycle" not in source
        assert "place_order(" not in source
        assert "save_autotrader_config_v3" not in source
