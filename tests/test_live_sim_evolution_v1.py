"""Evolving cohort and selectors are prospective, finite and broker-isolated."""
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path

import pytest
from database import connect
from live_sim_lab_store_v1 import (
    ensure_lab_schema,seed_default_experiments,process_lab_cycle,lab_snapshot,
    MAX_ACTIVE_LAB_VARIANTS,
)
from live_sim_lab_evolution_v1 import (
    SELECTOR_KINDS,NEW_MODIFIERS,ensure_evolution_schema,_default_shadow_state,
    update_observation,_recent_return_pct,candidate_score,_choose,
    load_shadow_states,settle_shadow,run_evolution_maintenance,
    seed_trial_ledger,evolution_snapshot,_retire_weak,
)

START=datetime(2026,10,9,tzinfo=timezone.utc)


def _time(m):return START+timedelta(minutes=m)


def _variant(ending, *, exposure=0.5, trades=12):
    # Exactly 25 5m observations, all closed strictly before current decisions.
    samples=[[_time(5*i).isoformat(),10000+(ending-10000)*i/24] for i in range(25)]
    return {"equity":ending, "peak":max(10000,ending),
            "max_drawdown":0.0,"trades":trades,"exposure":exposure,
            "pending":exposure,
            "_evo":{"bars":125,"samples":samples,"regime_stats":{
                "TREND":{"bars":125,"sum_return_fraction":(ending-10000)/10000}}}}


def test_invariants_and_full_finite_perturbation_queue(tmp_path):
    path=str(tmp_path/"lab.db")
    ensure_lab_schema(path)
    with connect(path) as db:
        ensure_evolution_schema(db)
        assert seed_default_experiments(
            db,instrument_id=17,market_name="Tech100",now=_time(0).isoformat())==72
        seed_trial_ledger(db,instrument_id=17,now=_time(0).isoformat())
        statuses={r["status"]:r["n"] for r in db.execute(
            "SELECT status,COUNT(*) AS n FROM lsim_perturbation_trials GROUP BY status"
        ).fetchall()}
        assert statuses=={"RUNNING":72,"QUEUED":180}
        seed_trial_ledger(db,instrument_id=17,now=_time(10).isoformat())
        assert db.execute("SELECT COUNT(*) AS n FROM lsim_perturbation_trials").fetchone()["n"]==252
    assert len(NEW_MODIFIERS)==4 and len(SELECTOR_KINDS)==3


def test_evidence_is_incremental_and_5min_sample_is_bounded():
    state={"equity":9998.0,"peak":10000,"trades":1}
    for m in range(1510):
        prev=state
        state={"equity":9998.0-m*0.01,"peak":10000,"trades":1}
        update_observation(state,prev,prior_regime="RANGE",bar_time=_time(m))
    evo=state["_evo"]
    assert evo["bars"]==1510
    assert len(evo["samples"])==288
    assert evo["positive_since_start_bars"]==0
    assert evo["positive_bar_returns"]==0
    assert evo["regime_stats"]["RANGE"]["bars"]==1510
    assert _recent_return_pct(evo,24)<0


def test_selector_needs_prospective_sample_and_strict_margin():
    strong=_variant(10100)
    weak=_variant(9970)
    assert candidate_score("RECENT",strong,"TREND") is not None
    assert candidate_score("REGIME",strong,"WARMUP") is None
    assert candidate_score("HYBRID",strong,"TREND") is not None
    s=_default_shadow_state()
    assert _choose("RECENT",s,{"strong":strong,"weak":weak},
                   regime="TREND",stamp=_time(130).isoformat())[0]=="strong"
    # A previously active champion cannot switch at first hint while cooling.
    s.update(selected_id="weak",last_switch_at=_time(100).isoformat())
    assert _choose("RECENT",s,{"strong":strong,"weak":weak},
                   regime="TREND",stamp=_time(130).isoformat())[0]=="weak"
    # Negative incumbent, large challenger advantage, cooldown expired.
    assert _choose("RECENT",s,{"strong":strong,"weak":weak},
                   regime="TREND",stamp=_time(170).isoformat())[0]=="strong"
    s["daily_switches"]=8
    assert _choose("RECENT",s,{"strong":strong,"weak":weak},
                   regime="TREND",stamp=_time(170).isoformat())[0]=="weak"


def test_shadow_selector_charges_next_open_only_and_is_idempotent(tmp_path):
    path=str(tmp_path/"lab.db")
    ensure_lab_schema(path)
    with connect(path) as db:
        ensure_evolution_schema(db)
        shadows=load_shadow_states(db,17)
        candidates={"strong":_variant(10200,exposure=1.0)}
        f={"regime":"TREND"}
        settle_shadow(db,instrument_id=17,states=shadows,candidates=candidates,
                      features=f,prior_regime="TREND",bar_time=_time(125),
                      open_price=100,close_price=100)
        assert shadows["RECENT"]["equity"]==10000
        assert shadows["RECENT"]["selected_id"] is None
        assert shadows["RECENT"]["pending_id"]=="strong"
        settle_shadow(db,instrument_id=17,states=shadows,candidates=candidates,
                      features=f,prior_regime="TREND",bar_time=_time(126),
                      open_price=100,close_price=101)
        assert shadows["RECENT"]["selected_id"]=="strong"
        assert shadows["RECENT"]["switches"]==1
        assert shadows["RECENT"]["equity"]==pytest.approx(
            10000*(1-0.0005)*(1-0.0007)*1.01)
        assert db.execute(
            "SELECT COUNT(*) AS n FROM lsim_selector_events").fetchone()["n"]>=1
        from live_sim_lab_evolution_v1 import persist_shadow_states
        persist_shadow_states(db,17,shadows)
    _,_,switches=evolution_snapshot(db_path=path)
    assert switches[0]["proposed_id"]=="strong"


def test_retirement_requires_multi_regime_evidence_and_consecutive_checks(tmp_path):
    path=str(tmp_path/"lab.db")
    ensure_lab_schema(path)
    with connect(path) as db:
        ensure_evolution_schema(db)
        seed_default_experiments(db,instrument_id=17,market_name="Tech100",now=_time(0).isoformat())
        seed_trial_ledger(db,instrument_id=17,now=_time(0).isoformat())
        first=db.execute("SELECT experiment_id FROM lsim_experiments LIMIT 1").fetchone()["experiment_id"]
        weak={"equity":9000.0,"peak":10000.0,"trades":12,
              "max_drawdown":0.1,"_evo":{"bars":1700,
              "regime_stats":{"TREND":{"bars":400,"sum_return_fraction":-0.02},
                              "RANGE":{"bars":400,"sum_return_fraction":-0.03}}}}
        for hour in range(3):
            retire=_retire_weak(db,17,{first:weak},_time(2000+hour*61))
            assert retire==(1 if hour==2 else 0)
        assert db.execute("SELECT status FROM lsim_experiments WHERE experiment_id=?",
                          (first,)).fetchone()["status"]=="RETIRED"
        journal=db.execute(
            "SELECT status,outcome_json FROM lsim_perturbation_trials WHERE experiment_id=?",
            (first,)).fetchone()
        assert journal["status"]=="RETIRED"
        assert json.loads(journal["outcome_json"])["reason"]=="NEVER_PROFITABLE_AND_NO_POSITIVE_REGIME_EDGE"
        seed_trial_ledger(db,instrument_id=17,now=_time(2300).isoformat())
        assert db.execute("SELECT status FROM lsim_perturbation_trials WHERE experiment_id=?",
                          (first,)).fetchone()["status"]=="RETIRED"



def test_negative_absolute_return_does_not_retire_regime_superior_variant(tmp_path):
    path=str(tmp_path/"lab.db")
    ensure_lab_schema(path)
    with connect(path) as db:
        ensure_evolution_schema(db)
        seed_default_experiments(db,instrument_id=17,market_name="Tech100",
                                 now=_time(0).isoformat())
        seed_trial_ledger(db,instrument_id=17,now=_time(0).isoformat())
        keys=[r["experiment_id"] for r in db.execute(
            "SELECT experiment_id FROM lsim_experiments ORDER BY experiment_id LIMIT 2"
        ).fetchall()]
        parent,challenger=keys
        db.execute("UPDATE lsim_perturbation_trials SET parent_id=? WHERE experiment_id=?",
                   (parent,challenger))
        def weak_stats(factor):
            return {"equity":8000.0,"peak":10000.0,"trades":20,
                    "_evo":{"bars":1800,"regime_stats":{
                        "TREND":{"bars":500,"sum_return_fraction":-0.03*factor},
                        "RANGE":{"bars":500,"sum_return_fraction":-0.04*factor}}}}
        challenger_state=weak_stats(0.5)
        parent_state=weak_stats(1.0)
        assert _retire_weak(db,17,{parent:parent_state,challenger:challenger_state},
                            _time(2400))==0
        assert db.execute(
            "SELECT weak_checks FROM lsim_perturbation_trials WHERE experiment_id=?",
            (challenger,)).fetchone()["weak_checks"]==0
        assert db.execute(
            "SELECT status FROM lsim_experiments WHERE experiment_id=?",
            (challenger,)).fetchone()["status"]=="ACTIVE"


def test_new_trials_are_prospective_rate_limited_and_never_exceed_cap(tmp_path):
    path=str(tmp_path/"lab.db")
    ensure_lab_schema(path)
    with connect(path) as db:
        ensure_evolution_schema(db)
        seed_default_experiments(db,instrument_id=17,market_name="Tech100",now=_time(0).isoformat())
        keys=[r["experiment_id"] for r in db.execute(
            "SELECT experiment_id FROM lsim_experiments").fetchall()]
        base=_variant(10040)
        base["_evo"]["bars"]=300
        s={k:base for k in keys}
        retired,promoted=run_evolution_maintenance(
            db,instrument_id=17,market_name="Tech100",states=s,now=_time(300))
        assert (retired,promoted)==(0,4)
        assert run_evolution_maintenance(
            db,instrument_id=17,market_name="Tech100",states=s,now=_time(320))==(0,0)
        for i in range(1,8):
            run_evolution_maintenance(
                db,instrument_id=17,market_name="Tech100",states=s,now=_time(300+61*i))
        assert db.execute("SELECT COUNT(*) AS n FROM lsim_experiments WHERE status='ACTIVE'").fetchone()["n"]==100
        assert db.execute("SELECT COUNT(*) AS n FROM lsim_perturbation_trials WHERE status='QUEUED'").fetchone()["n"]>0
        assert db.execute("SELECT COUNT(*) AS n FROM lsim_perturbation_trials WHERE status='RUNNING'").fetchone()["n"]==100
        # Timestamp must be later than initial variants, never backtested.
        first_new=db.execute(
            "SELECT started_at FROM lsim_perturbation_trials WHERE origin='BOUNDED_PERTURBATION' AND status='RUNNING' LIMIT 1"
        ).fetchone()["started_at"]
        assert first_new>=_time(300).isoformat()


def test_research_components_have_no_live_order_authority():
    root=Path(__file__).resolve().parent.parent
    for name in ("live_sim_lab_evolution_v1.py","live_sim_lab_store_v1.py"):
        data=(root/name).read_text()
        assert "from saxo_trading import" not in data
        assert "place_order(" not in data
        assert "run_v3_live_cycle" not in data
