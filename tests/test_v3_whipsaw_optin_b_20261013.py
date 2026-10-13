"""Exact Tech100-B LIVE whipsaw activation: explicit consent, one-shot, no orders."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from autotrader_v3_config_v1 import (
    AutoTraderConfigV3,load_autotrader_config_v3,save_autotrader_config_v3,
)
from autotrader_v3_whipsaw_live_v1 import (
    is_whipsaw_live_approved_v3,set_whipsaw_live_approval_v3,
)
import autotrader_v3_whipsaw_optin_b_20261013 as op


def instances():
    return (SimpleNamespace(
        instance_id=op.TRADER_B,account_id="account-b",
        uic=4912,asset_type="CfdOnIndex",market_name="US Tech 100 NAS"),)


def test_authorized_one_shot_targets_only_b_and_preserves_controls(tmp_path,monkeypatch):
    db=str(tmp_path/"test.db")
    monkeypatch.setattr(op,"load_v3_instances_v1",lambda **kw:instances())
    monkeypatch.setattr(op,"pending_order_v3",lambda **kw:None)
    old=AutoTraderConfigV3(
        trader_id=op.TRADER_B,strategy_key="aen21-sticky-fast-exit",
        timeframe="2m",regime_timeframe="15m",control_mode="Manuell",
        modifiers=("reset-on-loss",))
    a=AutoTraderConfigV3(
        trader_id="tech100-a",strategy_key="macd",
        timeframe="5m",modifiers=())
    save_autotrader_config_v3(old,db_path=db)
    save_autotrader_config_v3(a,db_path=db)
    assert op.apply_authorized_whipsaw_b_once(
        db_path=db,token="no permission")=="SKIP"
    assert not is_whipsaw_live_approved_v3(op.TRADER_B,db_path=db)
    assert op.apply_authorized_whipsaw_b_once(
        db_path=db,token=op.TRADER_B)=="ACTIVATED"
    result=load_autotrader_config_v3(op.TRADER_B,db_path=db)
    assert result.strategy_key==old.strategy_key
    assert result.timeframe==old.timeframe
    assert result.regime_timeframe==old.regime_timeframe
    assert result.control_mode==old.control_mode
    assert result.modifiers==("reset-on-loss","whipsaw")
    assert is_whipsaw_live_approved_v3(op.TRADER_B,db_path=db)
    assert load_autotrader_config_v3("tech100-a",db_path=db)==a
    # Human later removes the option/revokes approval; durable one-shot
    # marker must stop reactivation even while env flag is still present.
    save_autotrader_config_v3(old,db_path=db)
    set_whipsaw_live_approval_v3(op.TRADER_B,False,db_path=db)
    assert op.apply_authorized_whipsaw_b_once(
        db_path=db,token=op.TRADER_B)=="ALREADY_APPLIED"
    assert load_autotrader_config_v3(op.TRADER_B,db_path=db)==old
    assert not is_whipsaw_live_approved_v3(op.TRADER_B,db_path=db)


def test_pending_saxo_order_defers_user_optin(tmp_path,monkeypatch):
    db=str(tmp_path/"pending.db")
    monkeypatch.setattr(op,"load_v3_instances_v1",lambda **kw:instances())
    monkeypatch.setattr(op,"pending_order_v3",lambda **kw:{"state":"SUBMITTED"})
    save_autotrader_config_v3(
        AutoTraderConfigV3(trader_id=op.TRADER_B,strategy_key="macd",
                           timeframe="2m"),db_path=db)
    assert op.apply_authorized_whipsaw_b_once(
        db_path=db,token=op.TRADER_B)=="DEFER_PENDING"
    assert "whipsaw" not in load_autotrader_config_v3(op.TRADER_B,db_path=db).modifiers
    assert not is_whipsaw_live_approved_v3(op.TRADER_B,db_path=db)


def test_rejects_mismatched_instrument_and_unsupported_live_config(tmp_path,monkeypatch):
    db=str(tmp_path/"reject.db")
    monkeypatch.setattr(op,"pending_order_v3",lambda **kw:None)
    monkeypatch.setattr(
        op,"load_v3_instances_v1",
        lambda **kw:(SimpleNamespace(instance_id=op.TRADER_B,
            account_id="b",uic=4912,asset_type="CfdOnIndex",
            market_name="Silver ETF"),))
    with pytest.raises(RuntimeError,match="unexpected market"):
        op.apply_authorized_whipsaw_b_once(db_path=db,token=op.TRADER_B)
    monkeypatch.setattr(op,"load_v3_instances_v1",lambda **kw:instances())
    save_autotrader_config_v3(
        AutoTraderConfigV3(trader_id=op.TRADER_B,strategy_key="macd",
                           timeframe="Adaptiv"),db_path=db)
    with pytest.raises(RuntimeError,match="unsupported LIVE"):
        op.apply_authorized_whipsaw_b_once(db_path=db,token=op.TRADER_B)


def test_optin_has_no_broker_calls_and_serial_worker_only():
    root=Path(__file__).resolve().parent.parent
    src=(root/"autotrader_v3_whipsaw_optin_b_20261013.py").read_text()
    worker=(root/"worker.py").read_text()
    assert "place_order(" not in src
    assert "cancel_order(" not in src
    assert "set_live_enabled_v3" not in src
    assert "save_execution_policy_v3" not in src
    assert "apply_authorized_whipsaw_b_once(db_path=str(db_path))" in worker
