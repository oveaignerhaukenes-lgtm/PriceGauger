"""V2/V3 MACD Flip crossover parity and V3 inventory safety."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from autotrader_macd_dry_run_v2 import MacdObservationV2, SIGNAL_UP, SIGNAL_DOWN
from autotrader_macd_flip_policy_v2 import _cross_signal_v2
from autotrader_open_sizing_v2 import EntryInstrumentRulesV2
from autotrader_v3_closed_bar_driver_v1 import (
    align_closed_bar_target_v3, evaluate_closed_bar_once_v3,
)
from autotrader_v3_domain import TargetInventoryV3, AccountBoundaryV3, CapitalAllocationV3, ControlModeV3
from autotrader_v3_execution_plan_v1 import plan_execution_v3
from autotrader_v3_macd_flip_v1 import STRATEGY_KEY_V3, macd_flip_target_v3
from autotrader_v3_macd_trailing_v1 import MacdTrailingConfigV3
from autotrader_v3_pipeline_v1 import TraderV3, evaluate_trader_v3
from autotrader_v3_registry_v1 import (
    STRATEGIES_V3 as CATALOG, live_config_issues_v3, sim_config_issues_v3,
)
from autotrader_v3_strategy_registry_v1 import STRATEGIES_V3, evaluate_strategy_bar_v3
from autotrader_v3_strategy_sizing_v1 import strategy_amount_config_v3

BEGIN=datetime(2026,10,14,8,0,tzinfo=timezone.utc)


def obs(value,index=0):
    return MacdObservationV2(
        bar_time=BEGIN+timedelta(minutes=5*index),
        macd=float(value), signal=0.0,
    )


@pytest.mark.parametrize("previous,current",[
    (-2,1), (-.0001,.0001), (0,1),
    (2,-1), (.0001,-.0001), (0,-1),
    (1,2), (-1,-2), (1,0), (-1,0), (0,0),
])
def test_v3_signals_match_exact_v2_cross_inequalities(previous,current):
    before=obs(previous,1)
    now=obs(current,2)
    result=macd_flip_target_v3(
        current_target=TargetInventoryV3(0),
        observation=now,previous_observation=before,
        config=MacdTrailingConfigV3(tranche=.01,max_inventory=.10),
    )
    v2=_cross_signal_v2(before,now)
    expected=(.01 if v2==SIGNAL_UP else -.01 if v2==SIGNAL_DOWN else 0.0)
    assert result.target.amount==pytest.approx(expected)
    assert result.action==(
        "CROSS_UP" if v2==SIGNAL_UP else
        "CROSS_DOWN" if v2==SIGNAL_DOWN else "HOLD_UNTIL_CROSS"
    )


def test_no_initial_bootstrap_entry_no_trailing_and_exact_one_tranche():
    cfg=MacdTrailingConfigV3(tranche=.01,max_inventory=.1)
    original=TargetInventoryV3(.03)
    first=macd_flip_target_v3(current_target=original,observation=obs(-5),config=cfg)
    assert first.action=="HOLD_BOOTSTRAP"
    assert first.target==original
    stable=macd_flip_target_v3(
        current_target=original,observation=obs(.3,2),
        previous_observation=obs(.2,1),config=cfg)
    assert stable.action=="HOLD_UNTIL_CROSS"
    assert stable.target==original
    cross=macd_flip_target_v3(
        current_target=original,observation=obs(-.3,3),
        previous_observation=obs(.2,2),config=cfg)
    assert cross.action=="CROSS_DOWN"
    assert cross.target.amount==pytest.approx(-.01)
    assert abs(cross.target.amount)<cfg.max_inventory


def test_cross_does_not_scale_even_after_many_bars():
    cfg=MacdTrailingConfigV3(tranche=.01,max_inventory=.25)
    positions=[-1,-2,-3,-4,1,2,3,4,-1,-2]
    current=TargetInventoryV3(0)
    last=None
    recorded=[]
    for index,value in enumerate(positions):
        d=macd_flip_target_v3(current_target=current,
                              observation=obs(value,index),
                              previous_observation=last,config=cfg)
        current=d.target
        last=obs(value,index)
        recorded.append((d.action,current.amount))
    assert recorded[4]==("CROSS_UP",.01)
    assert recorded[8]==("CROSS_DOWN",-.01)
    assert all(abs(q)<=.01 for _,q in recorded)


def test_mapped_v3_registry_and_safe_live_sim_capabilities():
    spec=next(x for x in CATALOG if x.key=="macd-flip")
    assert spec.runtime_key==STRATEGY_KEY_V3
    assert spec.runtime_ready
    assert "Flip" in spec.label
    assert STRATEGY_KEY_V3 in STRATEGIES_V3
    assert STRATEGIES_V3[STRATEGY_KEY_V3].live_route_enabled
    for f in (live_config_issues_v3,sim_config_issues_v3):
        assert f(strategy_key="macd-flip",timeframe="5m",
                 control_mode="Manuell",modifiers=())==()
        assert "Adaptiv" in " | ".join(f(
            strategy_key="macd-flip",timeframe="Adaptiv",
            control_mode="Manuell",modifiers=()))


def test_saxo_minimum_one_tranche_and_finer_precision_fails_closed():
    def rules(decimals,min_qty,step):
        return EntryInstrumentRulesV2(
            uic=4912,asset_type="CfdOnIndex",currency="USD",
            is_tradable=True,non_tradable_reason="None",
            amount_decimals=decimals,minimum_amount=min_qty,
            increment_size=step,contract_size=1.0,
            supported_order_types=("Market",),amount_quantum=10**-decimals,
            reference_minimum_amount=min_qty,minimum_order_value=None,
        )
    config=strategy_amount_config_v3(
        strategy_key=STRATEGY_KEY_V3,rules=rules(2,.01,.01))
    assert config.tranche==.01 and config.max_inventory==.10
    d=macd_flip_target_v3(
        current_target=TargetInventoryV3(0),observation=obs(1,2),
        previous_observation=obs(-1,1),config=config)
    assert d.target.amount==.01  # ten allowed tranches never means ten are bought
    with pytest.raises(ValueError,match="finer than V3 inventory precision"):
        strategy_amount_config_v3(
            strategy_key=STRATEGY_KEY_V3,rules=rules(3,.001,.001))


def test_confirmed_v3_flat_before_reversal_without_direct_net_order():
    trader=TraderV3(
        trader_id="flip-test",account=AccountBoundaryV3("paper-1",4912,"CfdOnIndex"),
        strategy_key=STRATEGY_KEY_V3,mode=ControlModeV3.DETERMINISTIC,
        capital_allocation=CapitalAllocationV3(100.0),
    )
    decision=macd_flip_target_v3(
        current_target=TargetInventoryV3(.01),
        observation=obs(-1,2),previous_observation=obs(1,1))
    snapshot=evaluate_trader_v3(
        trader=trader,base_target=decision.target,
        actual_inventory=TargetInventoryV3(.01),modifiers=()).snapshot
    plan=plan_execution_v3(snapshot)
    assert [x.action for x in plan.steps]==["CLOSE","CONFIRM_FLAT","OPEN"]
    assert plan.steps[0].amount==.01
    assert plan.steps[-1].amount==.01
    # Only the first step may be sent in a live worker cycle; after
    # pending-order reconciliation the next cycle can OPEN from exact FLAT.
    after=evaluate_trader_v3(
        trader=trader,base_target=decision.target,
        actual_inventory=TargetInventoryV3(0.0),modifiers=()).snapshot
    assert [x.action for x in plan_execution_v3(after).steps]==["OPEN"]


def test_v3_persistent_driver_once_per_closed_bar_and_reboot(tmp_path):
    path=str(tmp_path/"flip.db")
    trader="flip-driver"
    one=evaluate_strategy_bar_v3(
        strategy_key=STRATEGY_KEY_V3,trader_id=trader,observation=obs(-1,1),
        db_path=path)
    assert one.is_new and one.decision.action=="HOLD_BOOTSTRAP"
    duplicate=evaluate_strategy_bar_v3(
        strategy_key=STRATEGY_KEY_V3,trader_id=trader,observation=obs(-1,1),
        db_path=path)
    assert not duplicate.is_new and duplicate.decision.action=="HOLD_DUPLICATE"
    up=evaluate_strategy_bar_v3(
        strategy_key=STRATEGY_KEY_V3,trader_id=trader,observation=obs(1,2),
        db_path=path)
    assert up.is_new and up.decision.action=="CROSS_UP"
    assert up.decision.target.amount==.01
    hold=evaluate_strategy_bar_v3(
        strategy_key=STRATEGY_KEY_V3,trader_id=trader,observation=obs(2,3),
        db_path=path)
    assert hold.decision.action=="HOLD_UNTIL_CROSS"
    assert hold.decision.target.amount==.01
    down=evaluate_strategy_bar_v3(
        strategy_key=STRATEGY_KEY_V3,trader_id=trader,observation=obs(-1,4),
        db_path=path)
    assert down.decision.action=="CROSS_DOWN" and down.decision.target.amount==-.01
    assert not evaluate_strategy_bar_v3(
        strategy_key=STRATEGY_KEY_V3,trader_id=trader,observation=obs(-1,4),
        db_path=path).is_new
    # Broker-alignment on loss must not trigger stale re-entry.
    assert align_closed_bar_target_v3(trader_id=trader,target_amount=0.0,db_path=path)
    no_reentry=evaluate_strategy_bar_v3(
        strategy_key=STRATEGY_KEY_V3,trader_id=trader,observation=obs(-2,5),
        db_path=path)
    assert no_reentry.decision.action=="HOLD_UNTIL_CROSS"
    assert no_reentry.decision.target.amount==0.0


def test_no_v2_live_worker_activation_or_legacy_macd_alias():
    source=Path("autotrader_v3_macd_flip_v1.py").read_text()
    for forbidden in ("configured_live_pilot_client_v3","from database import","place_order(",
                      "run_v2_live_cycle","set_live_enabled"):
        assert forbidden not in source
    from autotrader_v3_registry_v1 import migrate_legacy_strategy_v3, strategy_v3
    assert migrate_legacy_strategy_v3("macd-5m-flip-control-shadow-v1") is None
    assert strategy_v3("macd").runtime_key=="macd-trailing-v1"
