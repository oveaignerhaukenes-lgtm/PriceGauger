from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from database import connect
from live_sim_lab_store_v1 import ensure_lab_schema
from live_sim_lab_analyst_v1 import (
    REPORT_PROMPT_VERSION, analyst_instructions, enough_evidence,
    prepare_evidence, request_analysis, run_daily_analyst,
)


def _variant(identifier, modifier="none", *, profit=0.0):
    return {
        "experiment_id":identifier,"last_bar":"2026-10-09T19:00:00+00:00",
        "family":"sticky","signal_tf":2,"regime_tf":15,"max_exposure":0.5,
        "modifier":modifier,"return_pct":profit,"max_drawdown_pct":1.2,
        "trades":4,"started_at":"2026-10-09T08:00:00+00:00",
    }


def test_paired_controls_are_matched_and_quantified():
    variants=[_variant("control"),_variant("candidate","impulse_exit",profit=2)]
    memory=[{"experiment_id":"control","regime":"TREND",
             "observed_bars":40,"sum_delta_nav":10}]
    evidence=prepare_evidence(variants,memory)
    assert len(evidence["paired_modifier_ablations"])==1
    assert evidence["paired_modifier_ablations"][0]["delta_nav_return_percentage_points"]==2
    assert evidence["paired_modifier_ablations"][0]["control_id"]=="control"


def test_four_tasks_no_execution_and_uncertainty():
    text=analyst_instructions()
    assert all(s in text for s in ("1)","2)","3)","4)","regime","IN­GEN".replace("\u00ad","")))
    assert "IKKE" in text and "ingen" not in ""  # explicit execution prohibition


def test_minimum_forward_regime_sample_required():
    variants=[_variant(str(i)) for i in range(6)]
    evidence=prepare_evidence(variants,[])
    assert not enough_evidence(evidence)
    memory=[{"experiment_id":"0","regime":"TREND",
             "observed_bars":31,"sum_delta_nav":3}]
    evidence=prepare_evidence(variants,memory)
    assert enough_evidence(evidence)


def test_request_once_uses_only_evidence_and_no_store():
    calls=[]
    def fake_post(url,*,headers,json,timeout):
        calls.append((url,headers,json,timeout))
        return SimpleNamespace(raise_for_status=lambda:None,
                               json=lambda:{"output":[{"content":[{"type":"output_text","text":"Analyse"}]}]})
    answer=request_analysis({"observed":6},api_key="testkey",post=fake_post)
    assert answer=="Analyse"
    assert len(calls)==1
    assert calls[0][2]["store"] is False
    assert "analytiker" in calls[0][2]["instructions"]


def test_daily_claim_is_idempotent_no_repeat_api_calls(tmp_path,monkeypatch):
    path=str(tmp_path/"lab.sqlite")
    ensure_lab_schema(path)
    variants=[_variant(str(i)) for i in range(6)]
    memory=[{"experiment_id":"0","regime":"TREND",
             "observed_bars":31,"sum_delta_nav":3}]
    monkeypatch.setattr("live_sim_lab_analyst_v1.lab_snapshot",
                        lambda **_:(variants,memory,[]))
    with connect(path) as db:
        db.execute(
            "INSERT INTO lsim_daily_reports(report_date,created_at,data_json) "
            "VALUES(?,?,?)",
            ("2026-10-09","2026-10-09",json.dumps({"interpretation_status":"PENDING_AI"}))
        )
    calls=[]
    def fake_post(url,*,headers,json,timeout):
        calls.append(url)
        return SimpleNamespace(raise_for_status=lambda:None,
                               json=lambda:{"output_text":"Fakta og hypoteser"})
    assert run_daily_analyst("2026-10-09",db_path=path,
                             api_key="fake",post=fake_post)=="READY"
    assert run_daily_analyst("2026-10-09",db_path=path,
                             api_key="fake",post=fake_post)=="READY"
    assert len(calls)==1
    with connect(path) as db:
        row=db.execute(
            "SELECT data_json FROM lsim_daily_reports WHERE report_date=?",
            ("2026-10-09",)
        ).fetchone()
    report=json.loads(row["data_json"])
    assert report["ai_interpretation"]=="Fakta og hypoteser"
    assert report["analysis_evidence"]["paired_comparisons"]==0


def test_failure_does_not_retry_billable_request(tmp_path,monkeypatch):
    path=str(tmp_path/"lab.sqlite")
    ensure_lab_schema(path)
    variants=[_variant(str(i)) for i in range(6)]
    memory=[{"experiment_id":"0","regime":"TREND",
             "observed_bars":31,"sum_delta_nav":3}]
    monkeypatch.setattr("live_sim_lab_analyst_v1.lab_snapshot",lambda **_:(variants,memory,[]))
    with connect(path) as db:
        db.execute("INSERT INTO lsim_daily_reports VALUES(?,?,?)",
                   ("2026-10-09","2026-10-09",json.dumps({"interpretation_status":"PENDING_AI"})))
    count=[]
    def fail_post(*args,**kwargs):
        count.append(1)
        raise TimeoutError("simulated timeout")
    assert run_daily_analyst("2026-10-09",db_path=path,
                             api_key="fake",post=fail_post)=="AI_FAILED"
    assert run_daily_analyst("2026-10-09",db_path=path,
                             api_key="fake",post=fail_post)=="AI_FAILED"
    assert len(count)==1
