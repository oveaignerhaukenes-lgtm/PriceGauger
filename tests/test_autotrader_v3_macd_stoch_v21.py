"""MACD+Stoch V2.1: one-variable BUILD isolation from existing LIVE V2."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from autotrader_macd_dry_run_v2 import MacdObservationV2
from autotrader_v3_domain import TargetInventoryV3
from autotrader_v3_macd_stoch_v2 import macd_stoch_v2_target_v3
from autotrader_v3_macd_stoch_v21 import (
    STRATEGY_KEY_V3, BUILD_SCORE_DELTA, macd_stoch_v21_target_v3,
)
from autotrader_v3_macd_trailing_v1 import MacdTrailingConfigV3
from autotrader_v3_strategy_registry_v1 import (
    STRATEGIES_V3, evaluate_strategy_bar_v3,
)
from autotrader_v3_registry_v1 import (
    strategy_v3, live_config_issues_v3, sim_config_issues_v3,
)
from autotrader_v3_strategy_sizing_v1 import strategy_amount_config_v3
from autotrader_open_sizing_v2 import EntryInstrumentRulesV2

ZERO=datetime(2026,10,15,9,0,tzinfo=timezone.utc)
FLAT_BARS=tuple(SimpleNamespace(high=101.,low=99.,close=100.) for _ in range(40))


def observation(value,minute=1):
    return MacdObservationV2(
        bar_time=ZERO+timedelta(minutes=minute),macd=value,signal=0.0)


def evaluate(strategy,current,now,previous,bars=FLAT_BARS,cfg=None):
    return strategy(
        current_target=TargetInventoryV3(current),
        observation=observation(now,1),
        previous_observation=(
            observation(previous,0) if previous is not None else None
        ),
        bars=bars,
        config=cfg or MacdTrailingConfigV3(),
    )


def pair(current,now,previous,bars=FLAT_BARS):
    return (
        evaluate(macd_stoch_v2_target_v3,current,now,previous,bars),
        evaluate(macd_stoch_v21_target_v3,current,now,previous,bars),
    )


def test_new_registry_live_and_sim_but_no_activation_or_broker_calls():
    assert STRATEGY_KEY_V3=="macd-stoch-v2-1"
    assert STRATEGY_KEY_V3 in STRATEGIES_V3
    assert STRATEGIES_V3[STRATEGY_KEY_V3].live_route_enabled
    assert "V2.1" in strategy_v3(STRATEGY_KEY_V3).label
    for tf in ("1m","2m","5m","10m","15m","30m"):
        assert live_config_issues_v3(
            strategy_key=STRATEGY_KEY_V3,timeframe=tf,
            control_mode="Manuell",modifiers=())==()
        assert sim_config_issues_v3(
            strategy_key=STRATEGY_KEY_V3,timeframe=tf,
            control_mode="Manuell",modifiers=())==()
    source=Path("autotrader_v3_macd_stoch_v21.py").read_text()
    for forbidden in ("place_order(","configured_live_pilot_client",
                      "set_live_authority_v3","from database import"):
        assert forbidden not in source
    assert BUILD_SCORE_DELTA==pytest.approx(.02)


@pytest.mark.parametrize("size", [0.,.01,.02])
def test_v21_preserves_v2_weak_and_opposing_flat(size):
    for score,prior in ((0.,0.),(-.9,.9),(.06,.06)):
        old,new=pair(size,score,prior)
        if old.action!="BUILD":
            assert new==old


def test_first_entry_is_exactly_identical_to_v2():
    old,new=pair(0.,1.,1.)
    assert old.action=="OPEN"
    assert new==old
    assert new.target.amount==.01
    old,new=pair(0.,-1.,-1.)
    assert new==old
    assert new.target.amount==-.01


def test_decelerating_strong_bullish_still_holds_existing_tranche():
    old,new=pair(.01,.8,1.)
    assert old.action=="BUILD" and old.target.amount==.02
    assert new.action=="HOLD_BUILD_DECELERATING"
    assert new.target.amount==.01
    assert new.composite_score==old.composite_score
    assert "V2.1" in new.reason


def test_decelerating_strong_bearish_holds_short_not_flips():
    old,new=pair(-.01,-.8,-1.)
    assert old.action=="BUILD" and old.target.amount==-.02
    assert new.action=="HOLD_BUILD_DECELERATING"
    assert new.target.amount==-.01


@pytest.mark.parametrize("sign", [-1.,1.])
def test_accelerating_strong_signal_still_builds_one_tranche(sign):
    old,new=pair(sign*.01,sign*1.3,sign*.8)
    assert old.action=="BUILD"
    assert new==old
    assert new.target.amount==pytest.approx(sign*.02)


def test_equal_momentum_cannot_add():
    old,new=pair(.01,1.,1.)
    assert old.action=="BUILD"
    assert new.action=="HOLD_BUILD_DECELERATING"
    assert new.target.amount==.01


def test_missing_previous_evidence_cannot_add():
    old,new=pair(.01,1.,None)
    assert old.action=="WAIT_CONFIRMATION"
    assert new==old


def test_v21_closes_on_opposite_and_zero_without_extra_delay():
    old,new=pair(.07,-2.,1.)
    assert old.action=="OPPOSITE_FLAT"
    assert new==old and new.target.amount==0
    old,new=pair(-.07,0.,-1.)
    assert old.action=="WEAK_FLAT"
    assert new==old and new.target.amount==0


def test_closed_bar_persistent_target_and_no_duplicate_extra_build(tmp_path):
    db=str(tmp_path/"v21.sqlite")
    trader="account-test-v21"
    def decide(i,score):
        return evaluate_strategy_bar_v3(
            strategy_key=STRATEGY_KEY_V3,trader_id=trader,
            observation=observation(score,i),
            bars=FLAT_BARS,db_path=db)
    a=decide(1,1.)
    assert a.decision.target.amount==0
    b=decide(2,1.)
    assert b.decision.action=="OPEN"
    assert b.decision.target.amount==.01
    c=decide(3,.8)
    assert c.decision.action=="HOLD_BUILD_DECELERATING"
    assert c.decision.target.amount==.01
    duplicate=decide(3,.8)
    assert not duplicate.is_new
    assert duplicate.decision.target.amount==.01
    d=decide(4,1.3)
    assert d.decision.action=="BUILD" and d.decision.target.amount==.02
    e=decide(5,-1.)
    assert e.decision.action=="OPPOSITE_FLAT"
    assert e.decision.target.amount==0


def test_saxo_sizing_is_identical_to_v2():
    rules=EntryInstrumentRulesV2(
        uic=4912,asset_type="CfdOnIndex",currency="USD",
        is_tradable=True,non_tradable_reason="None",
        amount_decimals=2,minimum_amount=.01,increment_size=.01,
        contract_size=1,supported_order_types=("Market",),
        amount_quantum=.01,reference_minimum_amount=.01,
        minimum_order_value=None)
    assert strategy_amount_config_v3(strategy_key=STRATEGY_KEY_V3,
                                    rules=rules)==strategy_amount_config_v3(
                                        strategy_key="macd-stoch-v2",rules=rules)


def test_v2_original_source_unmodified():
    assert STRATEGY_KEY_V3 != "macd-stoch-v2"
    src=Path("autotrader_v3_macd_stoch_v2.py").read_text()
    assert "macd_stoch_v2_target_v3" in src
    assert "macd-stoch-v2-1" not in src
