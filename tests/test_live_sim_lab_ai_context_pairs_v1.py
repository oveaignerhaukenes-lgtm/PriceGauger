"""User-selected, equal-start AI research pairs; no lookahead or LIVE authority."""
import json
from datetime import datetime,timedelta,timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from database import connect
from live_sim_lab_store_v1 import ensure_lab_schema
from live_sim_lab_context_ablation_v1 import ensure_context_lab_schema
from live_sim_lab_ai_context_pairs_v1 import (
    ARMS,_known_review,available_parents,enroll_pairs,ensure_pair_schema,
    gate_parent_target,pair_snapshot,settle_selected_pairs,
)
from live_sim_lab_ai_context_reviewer_v1 import (
    context_evidence,review_instructions,request_review,review_selected_pairs,
    _technical_evidence,
)

BASE=datetime(2026,10,13,12,0,tzinfo=timezone.utc)


def stamp(m):
    return (BASE+timedelta(minutes=m)).isoformat()


def setup_lab(tmp_path):
    path=str(tmp_path/"research.db")
    ensure_lab_schema(path)
    with connect(path) as db:
        ensure_context_lab_schema(db)
        ensure_pair_schema(db)
        for index in range(3):
            cfg={"family":"sticky","signal_tf":2,"regime_tf":15,
                 "modifier":"none","max_exposure":1.0,"cost_bps":5.0}
            key=f"research-{index}"
            db.execute("""
                INSERT INTO lsim_experiments(
                    experiment_id,instrument_id,market_name,family,signal_tf,
                    regime_tf,modifier,max_exposure,cost_bps,config_json,
                    engine_version,started_at,status)
                VALUES(?,4912,'Tech100','sticky',2,15,'none',1,5,?,
                       'unit',?,'ACTIVE')
            """,(key,json.dumps(cfg),stamp(-300)))
            db.execute(
                "INSERT INTO lsim_states(experiment_id,state_json) VALUES(?,?)",
                (key,json.dumps({"equity":10001.0,"exposure":1.0,
                                 "pending":1.0,"last_bar":stamp(4)})))
        db.execute("""
            INSERT INTO lsim_feature_cursors(
                instrument_id,market_name,last_bar_time,state_json)
            VALUES(4912,'Tech100',?,?)
        """,(stamp(4),json.dumps({
            "last_bar":stamp(4),"last_close":30000,
            "regime":"RANGE","tags":["WHIPSAW"],
            "returns":[-0.0001,0.0001]*15,
            "macd":{"2":{"hist":0.5,"prev_hist":0.3,"spread":1.0}}
        })))
    return path


def test_multi_enrollment_is_explicit_bounded_and_restart_is_new_trial(tmp_path):
    path=setup_lab(tmp_path)
    assert len(available_parents(db_path=path))==3
    assert enroll_pairs(["research-0","research-1"],
                        db_path=path,now=BASE)==2
    cohorts,tracks,points,reviews=pair_snapshot(db_path=path)
    assert len(cohorts)==2 and not tracks and not points
    original={x["experiment_id"]:x["trial_id"] for x in cohorts}
    assert enroll_pairs(["research-1","research-2"],
                        db_path=path,now=BASE+timedelta(minutes=1))==1
    cohorts,*_=pair_snapshot(db_path=path)
    assert {x["experiment_id"] for x in cohorts}=={"research-1","research-2"}
    assert next(x["trial_id"] for x in cohorts
                if x["experiment_id"]=="research-1")==original["research-1"]
    assert enroll_pairs(["research-0"],db_path=path,
                        now=BASE+timedelta(minutes=2))==1
    cohorts,*_=pair_snapshot(db_path=path)
    assert len(cohorts)==1
    assert cohorts[0]["trial_id"]!=original["research-0"]
    with pytest.raises(ValueError):
        enroll_pairs(["research-unknown"],db_path=path)
    with pytest.raises(ValueError):
        enroll_pairs([str(x) for x in range(7)],db_path=path)


def test_same_start_five_costed_tracks_apply_ai_only_later(tmp_path):
    path=setup_lab(tmp_path)
    enroll_pairs(["research-0"],db_path=path,now=BASE)
    with connect(path) as db:
        ensure_pair_schema(db)
        trial=db.execute("SELECT trial_id FROM lsim_ai_pair_enrollments").fetchone()["trial_id"]
        parents={"research-0":{"pending":1.0,"exposure":1.0}}
        assert settle_selected_pairs(
            db,instrument_id=4912,states=parents,
            bar_time=stamp(0),open_price=30000,close_price=30000)==0
        assert settle_selected_pairs(
            db,instrument_id=4912,states=parents,
            bar_time=stamp(1),open_price=30000,close_price=30000)==5
        # Future model review cannot influence this or earlier bar decisions.
        db.execute("""
            INSERT INTO lsim_ai_pair_reviews(
              trial_id,arm,source_bar,requested_at,completed_at,
              status,model,action,confidence,reason,evidence_json,coverage_json)
            VALUES(?,'CONTEXT_AI',?,?,?,'READY','fake','FLAT',0.9,
                   'Dated evidence','{}','{}')
        """,(trial,stamp(1),stamp(1),stamp(3)))
        assert _known_review(db,trial,"CONTEXT_AI",as_of=stamp(2)) is None
        assert settle_selected_pairs(
            db,instrument_id=4912,states=parents,
            bar_time=stamp(2),open_price=30000,close_price=30100)==5
        at_decision={x["arm"]:json.loads(x["state_json"]) for x in db.execute(
            "SELECT arm,state_json FROM lsim_ai_pair_tracks").fetchall()}
        # Model decision may set a future pending target but cannot alter
        # the return earned on the same bar as the evidence.
        assert at_decision["BASE"]["equity"]==pytest.approx(
            at_decision["CONTEXT_AI"]["equity"])
        # Review becomes actionable at bar close >= its recorded completion;
        # it changes pending inventory for the NEXT bar opening.
        assert settle_selected_pairs(
            db,instrument_id=4912,states=parents,
            bar_time=stamp(3),open_price=30100,close_price=30100)==5
        rows=db.execute(
            "SELECT arm,state_json FROM lsim_ai_pair_tracks"
        ).fetchall()
        results={x["arm"]:json.loads(x["state_json"]) for x in rows}
        assert set(results)==set(ARMS)
        # On the NEXT bar, the context overlay is already flat and pays
        # its additional exit turnover cost, so the NAVs may differ.
        assert results["BASE"]["equity"]>results["CONTEXT_AI"]["equity"]
        assert results["CONTEXT_AUTO"]["pending"]==0
        assert results["TECH_AUTO"]["pending"]==0
        assert results["BASE"]["pending"]==1.0
        assert results["CONTEXT_AI"]["pending"]==0.0
        assert results["TECH_AI"]["pending"]==1.0
        assert settle_selected_pairs(
            db,instrument_id=4912,states=parents,
            bar_time=stamp(3),open_price=30100,close_price=30100)==0
        assert settle_selected_pairs(
            db,instrument_id=4912,states=parents,
            bar_time=stamp(4),open_price=30100,close_price=30000)==5
        tracks={x["arm"]:json.loads(x["state_json"]) for x in db.execute(
            "SELECT arm,state_json FROM lsim_ai_pair_tracks").fetchall()}
        assert tracks["CONTEXT_AI"]["exposure"]==0
        assert tracks["BASE"]["exposure"]==1
        assert tracks["CONTEXT_AI"]["equity"]>tracks["BASE"]["equity"]
        assert tracks["TECH_AUTO"]["exposure"]==0
        assert tracks["CONTEXT_AUTO"]["exposure"]==0
    assert pair_snapshot(db_path=path)[0][0]["experiment_id"]=="research-0"


def test_gate_never_increases_or_reverses_parent():
    for parent in (-1.0,-0.6,0.0,0.5,1.0):
        assert gate_parent_target(parent,None)==parent
        assert gate_parent_target(parent,"KEEP")==parent
        assert gate_parent_target(parent,"HALF")==pytest.approx(parent/2)
        assert gate_parent_target(parent,"FLAT")==0.0


def test_news_and_macro_sources_are_point_in_time_and_not_surprises(tmp_path):
    path=setup_lab(tmp_path)
    with connect(path) as db:
        # Future-recorded summary must not contaminate current decisions.
        db.execute("""
            CREATE TABLE news_context_snapshots(
                as_of TEXT PRIMARY KEY,source_channel TEXT,source_post_count INTEGER,
                coverage_end TEXT,payload_json TEXT,recorded_at TEXT)
        """)
        db.execute("""
            INSERT INTO news_context_snapshots
            VALUES(?, 'Telegram', 3, ?, ?, ?)
        """,(stamp(0),stamp(0),
             json.dumps({"summary":"Observed energy situation",
                         "active_drivers":["Oil conflict"],"confirmation_quality":0.8}),
             stamp(8)))
        db.execute("""
            INSERT INTO lsim_ctx_macro_refresh(id,checked_at,status,errors_json)
            VALUES(1,?,'READY','[]')
        """,(stamp(0),))
        db.execute("""
            INSERT INTO lsim_ctx_macro_events(
                event_id,scheduled_at,seen_at,event_type,importance,source,source_url)
            VALUES('e1',?,?,'US_CPI','HIGH','BLS','https://www.bls.gov/')
        """,(stamp(30),stamp(0)))
        ctx=context_evidence(db,as_of=stamp(4))
        assert ctx["coverage"]["news"]=="MISSING"
        assert ctx["coverage"]["macro"]=="READY"
        assert ctx["coverage"]["geopolitics"]=="MISSING"
        assert ctx["sources"]["macro"]["events"][0]["event_type"]=="US_CPI"
        assert all("actual_value" not in event and "surprise" not in event
                   for event in ctx["sources"]["macro"]["events"])
        ctx2=context_evidence(db,as_of=stamp(10))
        assert ctx2["coverage"]["news"]=="AVAILABLE"
        assert ctx2["sources"]["news"]["source_posts"]==3


def test_llm_is_contextual_only_when_requested_and_strict_schema():
    technical=review_instructions(arm="TECH_AI")
    contextual=review_instructions(arm="CONTEXT_AI")
    assert "Ignore macro" in technical
    assert "geopolitical" in contextual
    seen={}
    class Response:
        def raise_for_status(self):
            pass
        def json(self):
            return {"output_text":json.dumps({
                "action":"HALF","autonomous_target":-1,"confidence":0.93,
                "reason":"Source coverage suggests more volatility"})}
    def post(url,**kw):
        seen.update(kw)
        return Response()
    result=request_review(
        {"technical":{"tags":["WHIPSAW"]},
         "context":{"coverage":{"macro":"MISSING"}}},
        arm="CONTEXT_AI",key="test",post=post)
    assert result["action"]=="HALF"
    assert result["autonomous_target"]==-1
    assert seen["json"]["store"] is False
    assert "tools" not in seen["json"]
    assert seen["json"]["text"]["format"]["type"]=="json_schema"
    assert seen["json"]["input"].find("WHIPSAW")>=0
    assert request_review(
        {},arm="TECH_AI",key="t",
        post=lambda url,**kw:type("R",(),{
            "raise_for_status":lambda self:None,
            "json":lambda self:{"output_text":json.dumps({
                "action":"FLAT","autonomous_target":1,"confidence":0.3,"reason":"uncertain"})}
        })()
    )["action"]=="KEEP"


def test_technical_input_has_no_news_and_reviewer_is_bounded(tmp_path):
    path=setup_lab(tmp_path)
    enroll_pairs(["research-0"],db_path=path,now=stamp(0))
    with connect(path) as db:
        enrollment=db.execute("SELECT trial_id FROM lsim_ai_pair_enrollments").fetchone()
        technical=_technical_evidence(
            db,trial_id=enrollment["trial_id"],experiment_id="research-0",
            instrument_id=4912,source_bar=stamp(4),now=BASE+timedelta(minutes=5))
        assert "context" not in technical
        assert "macd" in str(technical).lower()
    requests=[]
    def post(url,**kwargs):
        requests.append(kwargs["json"]["input"])
        class R:
            def raise_for_status(self):pass
            def json(self):
                return {"output_text":json.dumps({
                    "action":"KEEP","autonomous_target":1,"confidence":0.95,"reason":"No clear reason to intervene"})}
        return R()
    now=BASE+timedelta(minutes=5)
    assert review_selected_pairs(
        db_path=path,now=now,api_key="test",post=post)==1
    assert len(requests)==1
    assert '"context"' not in requests[0]
    assert review_selected_pairs(
        db_path=path,now=now,api_key="test",post=post)==0
    with connect(path) as db:
        rows=db.execute("SELECT arm,status FROM lsim_ai_pair_reviews "
                        "ORDER BY arm").fetchall()
        assert [(x["arm"],x["status"]) for x in rows]==[
            ("CONTEXT_AI","NO_CONTEXT"),("TECH_AI","READY")]


def test_no_real_trading_imports_and_ui_selects_multiple_baselines():
    root=Path(__file__).resolve().parent.parent
    for name in ("live_sim_lab_ai_context_pairs_v1.py",
                 "live_sim_lab_ai_context_reviewer_v1.py"):
        text=(root/name).read_text()
        assert "place_order(" not in text
        assert "run_v3_live_cycle_v1" not in text
        assert "autotrader_v3_live_runtime" not in text
    ui=(root/"pages/0_Live_Sim_Lab.py").read_text()
    assert "AI-strategilab · nyheter, makro og geopolitikk" in ui
    assert "max_selections=MAX_ENROLLED" in ui
    assert "enroll_pairs([" in ui
    assert "context_tabs=st.tabs([" in ui
    assert 'arm="TECH_AI" if tab_index==0 else "CONTEXT_AI"' in ui
    assert "render_lab_tv_series(" in ui
    assert "Autonom P/L %" in ui
    assert "TECH_AUTO" in ui and "CONTEXT_AUTO" in ui
    worker=(root/"live_sim_lab_worker_v1.py").read_text()
    assert "run_ai_context_pair_loop" in worker



def test_autonomous_ai_may_short_against_long_parent_with_full_paper_fills(tmp_path):
    path=setup_lab(tmp_path)
    enroll_pairs(["research-0"],db_path=path,now=BASE)
    with connect(path) as db:
        trial=db.execute("SELECT trial_id FROM lsim_ai_pair_enrollments").fetchone()["trial_id"]
        parent={"research-0":{"pending":1.0,"exposure":1.0}}
        assert settle_selected_pairs(
            db,instrument_id=4912,states=parent,bar_time=stamp(1),
            open_price=30000,close_price=30000)==5
        db.execute("""
            INSERT INTO lsim_ai_pair_reviews(
              trial_id,arm,source_bar,requested_at,completed_at,
              status,model,action,autonomous_target,confidence,reason,
              evidence_json,coverage_json)
            VALUES(?,'TECH_AI',?,?,?,'READY','test','KEEP',-1,0.95,
                   'independent bearish technical model','{}','{}')
        """,(trial,stamp(1),stamp(1),stamp(2)))
        assert settle_selected_pairs(
            db,instrument_id=4912,states=parent,bar_time=stamp(2),
            open_price=30000,close_price=30000)==5
        state={x["arm"]:json.loads(x["state_json"]) for x in db.execute(
            "SELECT arm,state_json FROM lsim_ai_pair_tracks").fetchall()}
        assert state["BASE"]["pending"]==1
        assert state["TECH_AI"]["pending"]==1
        assert state["TECH_AUTO"]["pending"]==-1
        assert state["CONTEXT_AUTO"]["pending"]==0
        assert settle_selected_pairs(
            db,instrument_id=4912,states=parent,bar_time=stamp(3),
            open_price=30000,close_price=29700)==5
        state={x["arm"]:json.loads(x["state_json"]) for x in db.execute(
            "SELECT arm,state_json FROM lsim_ai_pair_tracks").fetchall()}
        assert state["BASE"]["exposure"]==1
        assert state["TECH_AUTO"]["exposure"]==-1
        assert state["TECH_AUTO"]["equity"]>state["BASE"]["equity"]
        assert state["TECH_AUTO"]["trades"]==1
        assert state["TECH_AUTO"]["costs"]>0
