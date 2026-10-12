"""MACD+Stoch v2 composite score, safe closed-bar route and help contracts."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from autotrader_macd_dry_run_v2 import MacdObservationV2
from autotrader_v3_domain import TargetInventoryV3
from autotrader_v3_macd_trailing_v1 import MacdTrailingConfigV3
from autotrader_v3_macd_stoch_v1 import macd_stoch_target_v3
from autotrader_v3_macd_stoch_v2 import (
    STRATEGY_KEY_V3, composite_score_v3, macd_stoch_v2_target_v3,
    MACD_WEIGHT, STOCH_WEIGHT,
)
from autotrader_v3_strategy_registry_v1 import STRATEGIES_V3, evaluate_strategy_bar_v3
from autotrader_v3_registry_v1 import (
    STRATEGIES_V3 as CATALOG, live_config_issues_v3,
    sim_config_issues_v3, strategy_display_label_v3,
)
from autotrader_v3_strategy_sizing_v1 import strategy_amount_config_v3
from autotrader_open_sizing_v2 import EntryInstrumentRulesV2

DATE=datetime(2026,10,12,tzinfo=timezone.utc)


def bars(closes=None):
    closes = closes or [100.0]*40
    return tuple(SimpleNamespace(high=float(x)+1,low=float(x)-1,close=float(x))
                 for x in closes)


def obs(spread,time=0):
    return MacdObservationV2(bar_time=DATE+timedelta(minutes=5*time),
                             macd=float(spread),signal=0.0)


def decide(current,spread,prev,points=None,config=None):
    return macd_stoch_v2_target_v3(
        current_target=TargetInventoryV3(current),
        observation=obs(spread,1),
        previous_observation=obs(prev,0) if prev is not None else None,
        bars=points if points is not None else bars(),
        config=config or MacdTrailingConfigV3(),
    )


def test_registry_has_both_v1_and_v2_different_definitions():
    assert STRATEGY_KEY_V3 == "macd-stoch-v2"
    assert STRATEGY_KEY_V3 in STRATEGIES_V3
    assert STRATEGIES_V3[STRATEGY_KEY_V3].live_route_enabled is True
    assert STRATEGIES_V3["macd-stoch-v1"].live_route_enabled is True
    assert next(s for s in CATALOG if s.key==STRATEGY_KEY_V3).runtime_key==STRATEGY_KEY_V3
    assert live_config_issues_v3(strategy_key=STRATEGY_KEY_V3,timeframe="5m",
                                 control_mode="Manuell",modifiers=())==()
    assert sim_config_issues_v3(strategy_key=STRATEGY_KEY_V3,timeframe="5m",
                                control_mode="Manuell",modifiers=())==()
    assert strategy_display_label_v3(STRATEGY_KEY_V3,"5m")=="MACD+Stoch v2 · 5m"


def test_normalized_composite_is_weighted_and_bounded():
    assert MACD_WEIGHT==pytest.approx(0.70)
    assert STOCH_WEIGHT==pytest.approx(0.30)
    score,macd,stoch=composite_score_v3(obs(0.5),bars())
    assert score == pytest.approx(0.70*macd+0.30*stoch)
    assert 0 < score < 1
    assert macd > 0 and stoch==0
    reverse=composite_score_v3(obs(-0.5),bars())
    assert reverse[0]==pytest.approx(-score)
    assert composite_score_v3(obs(1),bars([100]*10)) is None
    assert composite_score_v3(obs(float("nan")),bars()) is None


def test_stochastic_contributes_to_composite_without_owning_direction():
    up=bars([100]*24+[99,98,97,96,95,94,93,92,91,90,91,94,99,106,115,126])
    kd=composite_score_v3(obs(0),up)
    assert kd is not None
    assert kd[1]==0
    assert kd[2] != 0
    assert kd[0]==pytest.approx(0.30*kd[2])


def test_needs_two_confirmed_closed_bars_before_entry():
    assert decide(0,3,None).action=="WAIT_CONFIRMATION"
    assert decide(0,3,-3).action=="WAIT_CONFIRMATION"
    first=decide(0,3,3)
    assert first.action=="OPEN"
    assert first.target.amount==pytest.approx(0.01)
    second=decide(0.01,3,3)
    assert second.action=="BUILD"
    assert second.target.amount==pytest.approx(0.02)


def test_opposite_signal_flattens_full_position_not_immediately_flip():
    reverse=decide(0.07,-3,3)
    assert reverse.action=="OPPOSITE_FLAT"
    assert reverse.target.amount==0
    down=decide(0,-3,-3)
    assert down.action=="OPEN"
    assert down.target.amount==-0.01


def test_deadband_flattens_instead_of_churning():
    calm=decide(0.05,0,0)
    assert calm.action=="WEAK_FLAT"
    assert calm.target.amount==0
    assert decide(0,0,0).target.amount==0


def test_limits_tranches_and_warmup_fails_flat():
    cfg=MacdTrailingConfigV3(tranche=0.05,max_inventory=0.15)
    result=decide(0.15,3,3,config=cfg)
    assert result.action=="HOLD_MAX"
    assert result.target.amount==pytest.approx(0.15)
    missing=decide(0.10,3,3,points=bars([100]*4))
    assert missing.action=="FLAT_WARMUP"
    assert missing.target.amount==0


def test_legacy_stoch_strategy_is_unchanged():
    prev=obs(1,0)
    observation=obs(2,1)
    original=macd_stoch_target_v3(
        current_target=TargetInventoryV3(0),
        observation=observation,previous_observation=prev,bars=bars())
    new=macd_stoch_v2_target_v3(
        current_target=TargetInventoryV3(0),
        observation=observation,previous_observation=prev,bars=bars())
    assert original.action != new.action


def test_closed_bar_driver_deduplicates_and_persists_exact_target(tmp_path):
    path=str(tmp_path/"pg.db")
    points=bars()
    out=evaluate_strategy_bar_v3(
        strategy_key=STRATEGY_KEY_V3,trader_id="v2-test",
        observation=obs(3,10),bars=points,db_path=path)
    assert out.is_new
    assert out.decision.target.amount==0
    next=evaluate_strategy_bar_v3(
        strategy_key=STRATEGY_KEY_V3,trader_id="v2-test",
        observation=obs(3,11),bars=points,db_path=path)
    assert next.is_new and next.decision.target.amount==pytest.approx(0.01)
    replay=evaluate_strategy_bar_v3(
        strategy_key=STRATEGY_KEY_V3,trader_id="v2-test",
        observation=obs(3,11),bars=points,db_path=path)
    assert not replay.is_new
    assert replay.decision.action=="HOLD_DUPLICATE"
    assert replay.decision.target.amount==pytest.approx(0.01)
    down=evaluate_strategy_bar_v3(
        strategy_key=STRATEGY_KEY_V3,trader_id="v2-test",
        observation=obs(-3,12),bars=points,db_path=path)
    assert down.is_new
    assert down.decision.target.amount==0


def test_all_catalog_strategies_have_descriptions_and_help_control():
    assert all(s.label.strip() and s.description.strip() for s in CATALOG)
    ui=Path("autotrader_v3_instance_controls_ui_v1.py").read_text()
    assert 'with a.popover("❔"' in ui
    assert "st.write(help_spec.description)" in ui


def test_no_broker_operations_in_strategy():
    content=Path("autotrader_v3_macd_stoch_v2.py").read_text()
    import re
    assert re.search(r"^\\s*(?:from|import)\\s+saxo", content, re.MULTILINE) is None
    assert "place_order(" not in content
    assert "cancel_order(" not in content
