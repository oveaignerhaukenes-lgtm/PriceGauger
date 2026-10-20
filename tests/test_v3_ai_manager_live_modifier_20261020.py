"""V3 LIVE AI overlay: opt-in, causal and reduction-only Saxo order intent."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from pathlib import Path

import pytest

from autotrader_v3_ai_decision_memory_v1 import record_ai_decision_v1
from autotrader_v3_ai_manager_live_v1 import (
    MODIFIER_KEY_V3, AILossManagerLiveModifierV3,
    AILiveAdviceV3, verified_live_ai_advice_v3,
)
from autotrader_v3_domain import TargetInventoryV3
from autotrader_v3_pipeline_v1 import (
    TraderV3, evaluate_trader_v3,
)
from autotrader_v3_domain import AccountBoundaryV3,ControlModeV3
from autotrader_v3_registry_v1 import live_config_issues_v3,LIVE_MODIFIERS_V3

NOW=datetime(2026,10,20,12,40,tzinfo=timezone.utc)
TRADER=TraderV3(
    "t",AccountBoundaryV3("acct",4912,"CfdOnIndex"),"macd-flip-v1",
    mode=ControlModeV3.DETERMINISTIC,
)


def insert_decision(db, *, direction="LONG", qty=.02,
                    strategy="macd-flip", timeframe="2m",
                    action="FLAT", confidence=.86, age=30,
                    instance_id="t",account_id="acct",instrument_id=42):
    stamp=NOW-timedelta(seconds=age)
    data={"snapshot":{
        "source":"V3_SHADOW_ACCOUNT_SCOPED",
        "strategy":strategy,"timeframe":timeframe,
        "position":{
            "direction":direction,"quantity_abs":qty,
            "saxo_open_pnl_account_currency":-8.},
    },"model_proposal":{"direction":"FLAT","target_exposure":0.}}
    record_ai_decision_v1(
        decision_id=f"shadow:{instance_id}:{age}",instance_id=instance_id,
        account_id=account_id,instrument_id=instrument_id,
        strategy_key=strategy,evaluated_at=stamp,evidence_as_of=stamp,
        model_id="test-model",mode="SHADOW",action=action,
        confidence=confidence,reason="Bearish impulse during MACD contraction",
        evidence=data,db_path=db)


def lookup(db, **kwargs):
    return verified_live_ai_advice_v3(
        instance_id=kwargs.get("instance_id","t"),
        account_id=kwargs.get("account_id","acct"),
        instrument_id=kwargs.get("instrument_id",42),
        strategy_key=kwargs.get("strategy_key","macd-flip"),
        timeframe=kwargs.get("timeframe","2m"),
        actual_amount=kwargs.get("actual_amount",.02),
        verified_open_pnl=kwargs.get("verified_open_pnl",-9.),
        now=kwargs.get("now",NOW),db_path=db)


def test_ai_modifier_is_selectable_with_normal_live_without_extra_approval():
    assert MODIFIER_KEY_V3 in LIVE_MODIFIERS_V3
    assert live_config_issues_v3(
        strategy_key="macd-flip",timeframe="2m",
        control_mode="Manuell",modifiers=("ai-loss-manager",))==()
    assert live_config_issues_v3(
        strategy_key="macd-histogram",timeframe="5m",
        control_mode="Manuell",modifiers=("ai-loss-manager",))==()


def test_fresh_loss_advice_identified_and_applied_only_to_held_side(tmp_path):
    db=str(tmp_path/"advice.db")
    insert_decision(db)
    advice=lookup(db)
    assert advice and advice.action=="FLAT"
    modifier=AILossManagerLiveModifierV3(actual_inventory=.02,advice=advice)
    result=evaluate_trader_v3(
        trader=TRADER,base_target=TargetInventoryV3(.02),
        actual_inventory=TargetInventoryV3(.02),modifiers=(modifier,))
    assert result.snapshot.risk_approved_target.amount==0.
    assert result.snapshot.pending_delta==-.02
    assert "AI FLAT" in result.transforms[0].reason
    # Do not interfere with the base strategy's earlier exit or reversal.
    for target in (0.,-.01,.01):
        assert modifier.apply(TRADER,TargetInventoryV3(target))[0].amount==target
    # An already FLAT broker position must never create an AI entry.
    assert AILossManagerLiveModifierV3(0.,advice).apply(
        TRADER,TargetInventoryV3(.02))[0].amount==.02


@pytest.mark.parametrize("change",[
    {"account_id":"other"}, {"instrument_id":444},
    {"strategy_key":"macd-histogram"},{"timeframe":"1m"},
    {"actual_amount":-.02},{"actual_amount":.01},
    {"verified_open_pnl":1.},{"verified_open_pnl":0.},
    {"now":NOW+timedelta(seconds=110)},
    {"now":NOW-timedelta(seconds=90)},
])
def test_foreign_recovered_stale_or_changed_advice_is_ignored(tmp_path,change):
    db=str(tmp_path/"evidence.db")
    insert_decision(db)
    assert lookup(db,**change) is None


def test_hold_does_not_resurrect_or_reverse_position(tmp_path):
    db=str(tmp_path/"hold.db")
    insert_decision(db,action="HOLD")
    advice=lookup(db)
    assert advice and advice.action=="HOLD"
    modifier=AILossManagerLiveModifierV3(actual_inventory=-.02,advice=advice)
    assert modifier.apply(TRADER,TargetInventoryV3(-.02))[0].amount==-.02


def test_reduce_one_lot_within_available_saxo_steps(tmp_path):
    db=str(tmp_path/"reduce.db")
    insert_decision(db,direction="SHORT",qty=.03,action="REDUCE")
    advice=lookup(db,actual_amount=-.03)
    assert advice is not None
    modifier=AILossManagerLiveModifierV3(-.03,advice)
    after,_=modifier.apply(TRADER,TargetInventoryV3(-.03))
    assert after.amount==-.02
    # One smallest 0.01 step must not round a half-sized target to an OPEN.
    tiny=AILossManagerLiveModifierV3(-.01,advice)
    assert tiny.apply(TRADER,TargetInventoryV3(-.01))[0].amount==-.01


def test_ai_reverse_proposal_exits_without_opening_other_side(tmp_path):
    db=str(tmp_path/"reverse.db")
    insert_decision(db,action="REVERSE")
    advice=lookup(db)
    assert advice is not None
    result=AILossManagerLiveModifierV3(.02,advice).apply(
        TRADER,TargetInventoryV3(.02))
    assert result[0].amount==0.


def test_low_confidence_and_nonnegative_evidence_never_execute(tmp_path):
    db=str(tmp_path/"weak.db")
    insert_decision(db,confidence=.4)
    assert lookup(db) is None


def test_latest_hold_cancels_older_exit(tmp_path):
    db=str(tmp_path/"newer.db")
    insert_decision(db,action="FLAT",age=60)
    insert_decision(db,action="HOLD",age=10)
    advice=lookup(db)
    assert advice and advice.action=="HOLD"


def test_live_ai_path_is_common_execution_chain_and_no_model_saxo_post():
    code=Path("autotrader_v3_live_runtime_v1.py").read_text()
    assert "'ai-loss-manager' in config.modifiers" in code
    assert "verified_live_ai_advice_v3(" in code
    assert "modifiers.append(AILossManagerLiveModifierV3(" in code
    assert "align_closed_bar_target_v3(" in code
    assert code.index("verified_live_ai_advice_v3(")<code.index("pipeline=evaluate_trader_v3(")
    assert code.index("pipeline=evaluate_trader_v3(")<code.index("plan=plan_execution_v3(snapshot)")
    assert code.index("plan=plan_execution_v3(snapshot)")<code.index("reserve_order_v3(")
    addon=Path("autotrader_v3_ai_manager_live_v1.py").read_text()
    assert "SaxoOrderRequest" not in addon
    assert "place_order(" not in addon
    assert "set_live_authority_v3(" not in addon


def test_shadow_manager_ui_differentiates_live_from_advisory():
    panel=Path("autotrader_v3_instance_inspection_v1.py").read_text()
    assert "live_ai_enabled=('ai-loss-manager' in config.modifiers)" in panel
    assert "AI Manager · LIVE" in panel
