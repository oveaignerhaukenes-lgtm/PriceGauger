"""V3 AI manager observes sustained broker losses, never enters LIVE order path."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
import autotrader_v3_ai_manager_shadow_v1 as ai
from autotrader_v3_ai_decision_memory_v1 import load_ai_decisions_v1


NOW=datetime(2026,10,19,20,0,tzinfo=timezone.utc)
INST=SimpleNamespace(instance_id="trader-1",account_id="saxo-a",
    instrument_id=101,uic=4912,asset_type="CfdOnIndex",
    market_name="US Tech100",enabled=True)


def test_persisted_loss_timer_cooldown_and_reset(tmp_path):
    db=str(tmp_path/"watch.db")
    data=dict(instance_id="a",identity="account|strategy|long:0.01",
              open_pnl=-2.,trigger_seconds=60,db_path=db)
    assert not ai.claim_due_loss_review_v1(**data,when=NOW)
    assert not ai.claim_due_loss_review_v1(**data,when=NOW+timedelta(seconds=45))
    assert ai.claim_due_loss_review_v1(**data,when=NOW+timedelta(seconds=70))
    assert not ai.claim_due_loss_review_v1(**data,when=NOW+timedelta(seconds=90))
    assert ai.claim_due_loss_review_v1(**data,when=NOW+timedelta(seconds=260))
    assert not ai.claim_due_loss_review_v1(
        **{**data,"open_pnl":3.},when=NOW+timedelta(seconds=290))
    assert not ai.claim_due_loss_review_v1(
        **data,when=NOW+timedelta(seconds=310))
    assert ai.claim_due_loss_review_v1(
        **data,when=NOW+timedelta(seconds=375))
    assert not ai.claim_due_loss_review_v1(
        **{**data,"identity":"different-position"},
        when=NOW+timedelta(seconds=400))
    assert not ai.claim_due_loss_review_v1(
        **data,when=NOW+timedelta(seconds=500))


def test_shadow_settings_individual_and_bounded(tmp_path):
    db=str(tmp_path/"settings.db")
    assert ai.shadow_settings_v1("a",db_path=db)=={
        "enabled":True,"trigger_seconds":60}
    ai.save_shadow_settings_v1(instance_id="a",enabled=False,
                               trigger_seconds=45,db_path=db)
    assert ai.shadow_settings_v1("a",db_path=db)=={
        "enabled":False,"trigger_seconds":45}
    assert ai.shadow_settings_v1("b",db_path=db)["trigger_seconds"]==60
    with pytest.raises(ValueError,match="15..180"):
        ai.save_shadow_settings_v1(instance_id="a",enabled=True,
                                   trigger_seconds=181,db_path=db)


def test_ai_shadow_genuine_saxo_pnl_and_persistent_model_rationale(
    tmp_path,monkeypatch,
):
    db=str(tmp_path/"shadow.db")
    # Saxo's exact account-scoped net position; there is no place-order method.
    row={"NetPositionBase":{"AmountLong":0.01,"AmountShort":0.,
          "Uic":4912,"AssetType":"CfdOnIndex"},
         "NetPositionView":{"CalculationReliability":"Ok",
                            "ProfitLossOnTradeInBaseCurrency":-8.}}
    class ReadOnlyBroker:
        calls=0
        def net_positions_exact(self,**kw):
            self.calls+=1
            assert kw=={"account_id":"saxo-a","uic":4912,
                        "asset_type":"CfdOnIndex"}
            return (row,)
    broker=ReadOnlyBroker()
    monkeypatch.setattr(ai,"live_authority_armed_v3",
                        lambda *_args,**_kwargs:True)
    monkeypatch.setattr(ai,"load_autotrader_config_v3",
                        lambda *_args,**_kwargs:SimpleNamespace(
                            strategy_key="macd-flip",timeframe="2m"))
    seen=[]
    def evidence(**kw):
        assert kw["broker_pnl"]==-8.
        assert kw["actual"]==0.01
        return kw["observed_at"],{
            "as_of":kw["observed_at"].isoformat(),
            "technical":{"macd_histogram_last_5":[1,.6,.4,.2,.1]},
            "position":{"saxo_open_pnl_account_currency":-8.},
        }
    monkeypatch.setattr(ai,"_technical_evidence",evidence)
    def model(snapshot):
        seen.append(snapshot)
        return {"direction":"FLAT","target_exposure":0.,
                "confidence":.78,"reason":"MACD fading as price falls"}
    def step(seconds,model_callback=model):
        return ai.review_shadow_instance_once_v1(
            instance=INST,broker=broker,when=NOW+timedelta(seconds=seconds),
            db_path=db,model_callback=model_callback,model="fake-technical")
    assert step(0)=="WAITING"
    assert step(35)=="WAITING"
    assert step(70)=="FLAT"
    assert step(90)=="WAITING"
    assert len(seen)==1
    logs=load_ai_decisions_v1(
        instance_id="trader-1",account_id="saxo-a",
        instrument_id=101,db_path=db)
    assert len(logs)==1
    assert logs[0]["action"]=="FLAT"
    assert logs[0]["mode"]=="SHADOW"
    assert logs[0]["reason"]=="MACD fading as price falls"
    assert len(logs[0]["evidence_hash"])==64
    assert broker.calls==4
    assert not load_ai_decisions_v1(
        instance_id="trader-1",account_id="another",
        instrument_id=101,db_path=db)


def test_unreliable_saxo_pnl_never_enters_ai_path(tmp_path,monkeypatch):
    db=str(tmp_path/"bad-pnl.db")
    monkeypatch.setattr(ai,"live_authority_armed_v3",
                        lambda *_args,**_kwargs:True)
    monkeypatch.setattr(ai,"load_autotrader_config_v3",
                        lambda *_args,**_kwargs:SimpleNamespace(
                            strategy_key="macd",timeframe="2m"))
    class Broker:
        def net_positions_exact(self,**kw):
            return ({"NetPositionBase":{"AmountLong":.01},
                     "NetPositionView":{"CalculationReliability":"StalePrice",
                        "ProfitLossOnTradeInBaseCurrency":-5.}},)
    with pytest.raises(ValueError,match="reliable"):
        ai.review_shadow_instance_once_v1(
            instance=INST,broker=Broker(),when=NOW,db_path=db,
            model_callback=lambda _:pytest.fail("no AI request"))


def test_model_is_not_allowed_to_send_saxo_or_change_live_state():
    source=Path("autotrader_v3_ai_manager_shadow_v1.py").read_text()
    for forbidden in ("place_order(", "_post(", "set_live_enabled_v3(",
                      "submit(", "cancel_order(", "plan_execution_v3("):
        assert forbidden not in source
    assert "request_technical_decision" in source
    assert "record_ai_decision_v1(" in source
    assert "MAX_REVIEWS_PER_HOUR" in source
    worker=Path("telegram_multi_worker.py").read_text()
    assert "run_v3_ai_shadow_forever_v1" in worker
    assert "name=\"pricegauger-v3-ai-shadow\"" in worker
