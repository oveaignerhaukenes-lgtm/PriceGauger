from dataclasses import replace
from datetime import datetime,timedelta,timezone
import pytest
from live_mirror_broker_v1 import MirrorTerms,MirrorAccount,MirrorQuote
from live_mirror_execution_v1 import decide_target, support_reason, ensure_execution_schema, _update
from live_mirror_validation_v1 import VerifiedFill,IntentOutcome,calibrate_fills,compare_holdout,AccountWindow,validate_account_pnl
from live_mirror_evolution_v1 import BASE,FeatureFrame,ReplayFold,evaluate_genome,evolve
from database import connect
import json
from types import SimpleNamespace

NOW=datetime(2026,11,25,10,tzinfo=timezone.utc)
TERMS=MirrorTerms(10,.05,1,1,0,.01,300)


def config():
    return {"strategy":{"strategy_key":"macd-stoch-v2-1","timeframe":"2m",
        "control_mode":"Manuell","modifiers_json":"[]","regime_timeframe":"5m",
        "exit_timeframe":"2m"},"missing_sources":[]}


def test_independent_strategy_calls_canonical_and_respects_stop(monkeypatch):
    import live_mirror_execution_v1 as m
    cfg=config()
    cfg["stop"]={"strategy_key":"macd-stoch-v2-1","mode":"STOP"}
    def strategy(**kwargs):
        assert kwargs["current_target"].amount==.01
        return SimpleNamespace(target=SimpleNamespace(amount=.02),action="BUILD",reason="test")
    monkeypatch.setitem(m.SUPPORTED,"macd-stoch-v2-1",strategy)
    a=MirrorAccount(300,.01,100)
    raw,target,action,_=decide_target(cfg,a,(),(),(object(),object()),now=NOW,terms=TERMS,market="Tech100")
    assert (raw,target,action)==(.02,.01,"STOP_VETO")
    assert support_reason(cfg) is None
    cfg["strategy"]["modifiers_json"]='["impulse-exit"]'
    assert support_reason(cfg) is None
    cfg["strategy"]["modifiers_json"]='["impulse-exit","account-loss-lock"]'
    assert support_reason(cfg)=="UNSUPPORTED_MODIFIERS_OR_MODE"


def test_atomic_cas_does_not_double_settle(tmp_path):
    path=str(tmp_path/"m.db")
    ensure_execution_schema(path)
    with connect(path) as db:
        db.execute("""INSERT INTO pg_live_mirror_session_v1 VALUES
            ('s','m','a','{}',?,300,TRUE,?,'{}',NULL,'WARMUP',0)""",
            (NOW.isoformat(),NOW.isoformat()))
    session={"session_id":"s","revision":0}
    a=MirrorAccount(300)
    kwargs=dict(db_path=path,last_bar=NOW.isoformat(),pending=None,account=a,status="NO_CHANGE",
                event={"bar":NOW.isoformat(),"decided_at":NOW.isoformat()})
    assert _update(session,**kwargs)
    assert not _update(session,**kwargs)
    with connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM pg_live_mirror_event_v1").fetchone()[0]==1


def calibration():
    samples=[VerifiedFill(str(i),"a","4912:CfdOnIndex","BUY",.01,
        NOW-timedelta(minutes=60-i),NOW-timedelta(minutes=60-i)+timedelta(seconds=3),
        102.2,100,102,NOW-timedelta(minutes=60-i)+timedelta(seconds=2),
        "SAXO_FINAL_FILL") for i in range(30)]
    return calibrate_fills(samples,frozen_at=NOW)


def test_calibration_and_holdout_missing_events_cannot_pass():
    c=calibration()
    assert c.latency_p50==3 and c.slippage_p50==pytest.approx(.2)
    live=[IntentOutcome("a",c.instrument_key,str(i),NOW+timedelta(minutes=i),
        .01,.01,"FILLED",102,NOW+timedelta(minutes=i,seconds=3),"BUY",.01,True)
        for i in range(100)]
    sim=[replace(x,fill_price=102.1,verified=False) for x in live]
    report=compare_holdout(c,live,sim)
    assert report["passed"] and not report["pnl_validated"]
    assert not compare_holdout(c,live,sim[:-10])["passed"]
    assert not compare_holdout(c,live,[replace(x,verified=False) for x in sim[:-1]])["pnl_validated"]
    with pytest.raises(ValueError):
        compare_holdout(c,[replace(live[0],decided_at=NOW-timedelta(seconds=1))],[])
    windows=[AccountWindow("a",NOW+timedelta(days=i),NOW+timedelta(days=i+1),
        300,301,0,300,300.9,0,True,True) for i in range(10)]
    assert validate_account_pnl(report,windows,frozen_at=NOW)["pnl_validated"]
    assert not validate_account_pnl(report,[replace(w,includes_all_costs=False) for w in windows],
                                    frozen_at=NOW)["pnl_validated"]


def test_evolution_1000_models_bounded_and_holdout_not_used_for_selection():
    calls=[]
    def evaluator(g,features):
        calls.append(features)
        return (1-abs(g.entry-.4),.2,10)
    folds=((NOW,NOW+timedelta(days=1),"train-a"),
           (NOW+timedelta(days=1),NOW+timedelta(days=2),"train-b"))
    holdout=(NOW+timedelta(days=2),NOW+timedelta(days=3),"holdout")
    with pytest.raises(ValueError):
        evolve(folds=folds,holdout=holdout,evaluate=evaluator,validation={"passed":True})
    result=evolve(folds=folds,holdout=holdout,evaluate=evaluator,
                  validation={"passed":True,"pnl_validated":True},population=1000,generations=2)
    assert result["generations"][0]["population"]==1000
    assert result["unique_genomes"]>=1000
    assert calls.count("holdout") in (1,2)
    assert all(x=="holdout" for x in calls[calls.index("holdout"):])
    assert result["status"]=="RESEARCH_ONLY_NO_PROMOTION"


def test_replay_uses_bid_ask_fees_and_shared_features():
    frames=[]
    for i,(score,bid) in enumerate(((.8,100),(.8,100),(-.8,100))):
        t=NOW+timedelta(minutes=i)
        q=MirrorQuote(t+timedelta(seconds=2),t+timedelta(seconds=2),bid,bid+2)
        frames.append(FeatureFrame(t,score,score,"BULL",(q,)))
    fold=ReplayFold(tuple(frames),300,TERMS)
    ret,dd,trades=evaluate_genome(BASE,fold)
    assert trades==2 and ret<0 and dd>0


def test_impulse_exit_uses_only_simulated_position_and_preserves_bar_cursor(tmp_path,monkeypatch):
    import live_mirror_execution_v1 as m
    from autotrader_v3_protective_live_v1 import ProtectiveEvidenceV3
    path=str(tmp_path/"m.db")
    ensure_execution_schema(path)
    cursor=NOW.isoformat()
    with connect(path) as db:
        db.execute("""INSERT INTO pg_live_mirror_session_v1 VALUES
            ('s','m','a','{}',?,300,TRUE,?, ?,NULL,'WARMUP',0)""",
            (cursor,cursor,json.dumps(dict(cash_nok=300,inventory=.01,entry_price=100,
                fees_nok=0.,realized_nok=0.))))
    cfg=config()
    cfg["strategy"]["modifiers_json"]='["impulse-exit"]'
    def pause(cfg,account,previous,now,db_path,cache):
        assert account.inventory==.01
        return ProtectiveEvidenceV3("impulse-exit","IMPULSE_PAUSE","test"),{"status":"IMPULSE_PAUSE","quiet_since":None}
    monkeypatch.setattr(m,"_impulse",pause)
    clock=NOW+timedelta(seconds=12)
    session=m._read_sessions(path)[0]
    assert m._advance(session,{},cfg,TERMS,clock,path,{})
    session=m._read_sessions(path)[0]
    assert session["last_bar"]==cursor
    assert json.loads(session["pending_json"])["kind"]=="PROTECTIVE_TICK"
    monkeypatch.setattr(m,"_quotes",lambda *args:(MirrorQuote(clock+timedelta(seconds=2),clock+timedelta(seconds=2),99,100),))
    assert m._advance(session,{},cfg,TERMS,clock+timedelta(seconds=2),path,{})
    session=m._read_sessions(path)[0]
    assert session["last_bar"]==cursor
    state=json.loads(session["state_json"])
    assert state["inventory"]==0 and state["impulse"]["status"]=="IMPULSE_PAUSE"
