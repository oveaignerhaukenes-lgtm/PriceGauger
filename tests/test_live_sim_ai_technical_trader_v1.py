"""AI Technical Trader PAPER isolation, durable evaluation and status tests."""
import json
from datetime import datetime,timedelta,timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from database import connect
from live_sim_ai_technical_status_v1 import (
    classify_ai_status,record_ai_heartbeat,load_ai_technical_status,
    load_ai_decision_feed,
)
from live_sim_ai_technical_trader_v1 import (
    _initial_state,_mark_account,_event_kind,risk_gate,
    request_technical_decision,process_ai_paper_cycle,
)
from live_sim_hyper_quotes_v1 import HyperQuoteRecorder
from live_sim_hyper_vigilant_v1 import process_hyper_cycle

START=datetime(2026,10,12,19,0,tzinfo=timezone.utc)


def ts(i):
    return (START+timedelta(seconds=i)).isoformat()


def sample(i,price):
    return SimpleNamespace(
        market="US Tech 100 NAS",uic=4912,asset_type="CfdOnIndex",
        bid=price-0.8,ask=price+0.8,observed_at=ts(i))


class DummyResponse:
    def __init__(self,payload):
        self.payload=payload
    def raise_for_status(self):
        pass
    def json(self):
        return self.payload


def test_ai_model_response_is_numeric_schema_and_technical_only():
    observed={}
    def post(url,**kwargs):
        observed.update(kwargs)
        return DummyResponse({"output_text":json.dumps({
            "direction":"LONG","target_exposure":1,
            "confidence":0.82,"reason":"K opp, MACD hist positive"})})
    result=request_technical_decision(
        evidence={"price":{"mid":30000},"technical":{"stochastic_k":80}},
        key="test-key",post=post)
    assert result["target_exposure"]==1
    assert "json_schema"==observed["json"]["text"]["format"]["type"]
    instructions=observed["json"]["instructions"]
    assert "technical" in instructions.lower()
    assert "No" not in instructions or "never" in instructions.lower()
    assert observed["json"]["store"] is False
    assert "tools" not in observed["json"]
    assert "trade/v2" not in observed["json"]["input"]


@pytest.mark.parametrize("response",[
    {"direction":"SHORT","target_exposure":1,"confidence":0.9,"reason":"x"},
    {"direction":"LONG","target_exposure":3,"confidence":0.9,"reason":"x"},
    {"direction":"LONG","target_exposure":1,"confidence":1.4,"reason":"x"},
    {"direction":"FLAT","target_exposure":-1,"confidence":0.9,"reason":"x"},
    {"direction":"LONG","target_exposure":1,"confidence":0.9,"reason":""},
])
def test_invalid_ai_response_fails_closed(response):
    with pytest.raises(ValueError):
        request_technical_decision(
            evidence={},key="test",
            post=lambda url,**kwargs:DummyResponse(
                {"output_text":json.dumps(response)}))


def test_risk_gate_prevents_flip_and_whipsaw_expansion():
    confident=lambda direction,target:{
        "direction":direction,"target_exposure":target,
        "confidence":0.9,"reason":"observed"}
    assert risk_gate(proposal=confident("SHORT",-1),current=1,
                     whipsaw=False)==(0.0,"FLAT_BEFORE_REVERSE")
    assert risk_gate(proposal=confident("LONG",1),current=0,
                     whipsaw=False)==(0.5,"PAPER_RISK_APPROVED")
    assert risk_gate(proposal=confident("LONG",1),current=0,
                     whipsaw=True)==(0.0,"WHIPSAW_BLOCK_ENTRY")
    assert risk_gate(proposal=confident("FLAT",0),current=1,
                     whipsaw=True)==(0.0,"PAPER_RISK_APPROVED")
    low=confident("LONG",1)
    low["confidence"]=0.1
    assert risk_gate(proposal=low,current=0,whipsaw=False)[0]==0


def test_one_minute_loss_triggers_independent_of_routine():
    state=_initial_state(quote_time=ts(0),mid=30000,baseline_nav=10000)
    state["last_evaluated_at"]=ts(0)
    state["negative_since"]=ts(29)
    assert _event_kind(state,START+timedelta(seconds=88)) is None
    # 90s minimum request gap still applies; 60s sustained adverse move now valid.
    assert _event_kind(state,START+timedelta(seconds=91))=="LOSS_60S"
    state["negative_since"]=None
    assert _event_kind(state,START+timedelta(seconds=91)) is None
    assert _event_kind(state,START+timedelta(seconds=185))=="TECHNICAL_REVIEW"


def test_paper_intent_fills_only_on_real_later_quote_and_is_idempotent():
    state=_initial_state(quote_time=ts(0),mid=30000,baseline_nav=None)
    state["pending"]=0.5
    state["pending_as_of"]=ts(1)
    item={"quote_at":ts(1),"bid":30000,"ask":30002}
    unchanged,traded=_mark_account(state,item)
    assert not traded and unchanged["exposure"]==0
    item2={"quote_at":ts(2),"bid":30000,"ask":30002}
    filled,traded=_mark_account(unchanged,item2)
    assert traded and filled["exposure"]==0.5
    assert filled["equity"]<10000 and filled["trades"]==1
    repeat,traded=_mark_account(filled,item2)
    assert not traded and repeat==filled
    # Disconnection cannot fill a hanging decision.
    filled["pending"]=-0.5
    filled["pending_as_of"]=ts(2)
    gap,traded=_mark_account(filled,{"quote_at":ts(12),"bid":30000,"ask":30002})
    assert not traded and gap["exposure"]==0.5
    assert gap["data_gaps"]==1


def test_status_is_truthful_about_key_feed_model_and_worker():
    at=START
    hb={"tick_at":ts(0),"key_configured":1,"result":"OK",
        "error_type":""}
    assert classify_ai_status(now=at)["code"]=="NOT_STARTED"
    assert classify_ai_status(heartbeat=hb,now=at+timedelta(seconds=26))["code"]=="OFFLINE"
    assert classify_ai_status(heartbeat=dict(hb,key_configured=0),now=at)["code"]=="NO_KEY"
    assert classify_ai_status(heartbeat=dict(hb,result="ERROR",error_type="OSError"),
                              now=at)["code"]=="ENGINE_ERROR"
    assert classify_ai_status(heartbeat=hb,now=at)["code"]=="WAIT_FEED"
    fresh=classify_ai_status(heartbeat=hb,quote_at=ts(0),now=at)
    assert fresh["code"]=="WARMUP" and fresh["active"]
    working={"as_of":ts(0),"requested_at":ts(0),"event_kind":"TECHNICAL_REVIEW",
             "model_status":"CLAIMED","target":None}
    assert classify_ai_status(
        heartbeat=hb,quote_at=ts(0),decision=working,now=at)["code"]=="THINKING"
    accepted=dict(working,model_status="READY",target=0.5)
    live=classify_ai_status(heartbeat=hb,quote_at=ts(0),
                            decision=accepted,now=at)
    assert live["code"]=="ACTIVE" and live["last_target"]==0.5
    wrong=dict(working,model_status="STALE_RESPONSE")
    assert classify_ai_status(
        heartbeat=hb,quote_at=ts(0),decision=wrong,now=at)["code"]=="MODEL_ERROR"


def test_heartbeat_persists_and_front_end_uses_worker_key_not_web_env(tmp_path):
    path=str(tmp_path/"ai.sqlite")
    record_ai_heartbeat(db_path=path,key_configured=False,now=START)
    health=load_ai_technical_status(db_path=path,now=START)
    assert health["code"]=="NO_KEY"
    record_ai_heartbeat(db_path=path,key_configured=True,now=START)
    assert load_ai_technical_status(db_path=path,now=START)["code"]=="WAIT_FEED"
    assert load_ai_decision_feed(db_path=path)==[]


def test_prospective_ai_portfolio_and_call_claim_on_fresh_1s_quotes(tmp_path):
    path=str(tmp_path/"lab.db")
    capture=HyperQuoteRecorder(path)
    for i in range(65):
        price=30000+i*.5
        assert capture.observe(sample(i,price),tradable=True,
                               now=START+timedelta(seconds=i))
    # Hyper indicators may warm up from past quotes; no past AI P/L is booked.
    process_hyper_cycle(db_path=path,now=START+timedelta(seconds=65))
    calls=[]
    def post(url,**kwargs):
        calls.append(kwargs)
        return DummyResponse({"output_text":json.dumps({
            "direction":"LONG","target_exposure":1.0,
            "confidence":0.92,"reason":"Rising K and price"})})
    assert process_ai_paper_cycle(db_path=path,now=START+timedelta(seconds=64),
                                  api_key="t",post=post)==1
    assert not calls
    # One brand-new quote: model may issue next-quote-only PAPER intent.
    assert capture.observe(sample(65,30040),tradable=True,
                           now=START+timedelta(seconds=65))
    assert process_ai_paper_cycle(db_path=path,now=START+timedelta(seconds=65),
                                  api_key="t",post=post)==1
    assert len(calls)==1
    with connect(path) as db:
        state=json.loads(db.execute(
            "SELECT state_json FROM lsim_ai_technical_accounts").fetchone()["state_json"])
        assert state["exposure"]==0
        assert state["pending"]==0.5
        assert state["accepted_decisions"]==1
    assert process_ai_paper_cycle(db_path=path,now=START+timedelta(seconds=65),
                                  api_key="t",post=post)==0
    assert len(calls)==1
    assert capture.observe(sample(66,30041),tradable=True,
                           now=START+timedelta(seconds=66))
    process_ai_paper_cycle(db_path=path,now=START+timedelta(seconds=66),
                           api_key="t",post=post)
    with connect(path) as db:
        state=json.loads(db.execute(
            "SELECT state_json FROM lsim_ai_technical_accounts").fetchone()["state_json"])
        assert state["exposure"]==0.5
        assert state["trades"]==1


def test_lab_right_ticker_and_global_status_panel_have_no_live_order_authority():
    root=Path(__file__).resolve().parent.parent
    lab=(root/"pages/0_Live_Sim_Lab.py").read_text()
    widget=(root/"autotrader_status_widget_v1.py").read_text()
    worker=(root/"live_sim_lab_worker_v1.py").read_text()
    assert "ai_left, ai_right = st.columns" in lab
    assert '@st.fragment(run_every="10s")' in lab
    assert "load_ai_decision_feed(limit=30)" in lab
    assert "AI Trader · PAPER" in widget
    assert "ai_trader" in widget
    assert "load_ai_technical_status()" in widget
    assert "record_ai_heartbeat(" in worker
    assert "place_order(" not in lab
    assert "place_order(" not in widget
    assert "place_order(" not in (
        root/"live_sim_ai_technical_trader_v1.py").read_text()
