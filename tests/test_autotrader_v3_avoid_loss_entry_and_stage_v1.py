"""MACD 2m entry policy and durable preflight -> Saxo OPEN lifecycle evidence."""
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
from pathlib import Path

import pytest

from autotrader_macd_dry_run_v2 import MacdObservationV2
from autotrader_v3_avoid_loss_strategy_v1 import avoid_loss_macd_entry_v1
from autotrader_v3_domain import TargetInventoryV3
from autotrader_v3_registry_v1 import (
    live_config_issues_v3,sim_config_issues_v3,strategy_v3,
)
from autotrader_v3_strategy_registry_v1 import (
    STRATEGIES_V3,evaluate_strategy_bar_v3,
)
from autotrader_v3_avoid_loss_state_v1 import (
    stage_entry_preflight_v1,staged_entry_for_reconciled_order_v1,
    register_confirmed_entry_anchor_v1,retire_confirmed_flat_v1,
    save_avoid_loss_exit_bar_v1,load_avoid_loss_exit_bar_v1,
)
from autotrader_v3_avoid_loss_v1 import ConfirmedPositionV1
from autotrader_v3_order_guard_v1 import reserve,mark

T0=datetime(2026,10,16,8,0,tzinfo=timezone.utc)


def observation(spread,t):
    return MacdObservationV2(bar_time=T0+timedelta(minutes=t),
                             macd=spread,signal=0)


def bars(n=16,trend=0.5):
    return tuple(SimpleNamespace(open=100+i*trend,high=101+i*trend,
        low=99+i*trend,close=100+i*trend) for i in range(n))


def test_entry_is_one_tranche_only_macd2m_and_runtime_selectable():
    assert strategy_v3("avoid-loss-v1").runtime_ready
    assert STRATEGIES_V3["avoid-loss-v1"].live_route_enabled
    for issues in (live_config_issues_v3(strategy_key="avoid-loss-v1",
                   timeframe="2m",control_mode="Manuell",modifiers=()),
                   sim_config_issues_v3(strategy_key="avoid-loss-v1",
                   timeframe="2m",control_mode="Manuell",modifiers=())):
        assert issues==()
    for tf in ("1m","5m","15m","Adaptiv"):
        assert live_config_issues_v3(strategy_key="avoid-loss-v1",timeframe=tf,
                  control_mode="Manuell",modifiers=())
    assert live_config_issues_v3(strategy_key="avoid-loss-v1",timeframe="2m",
                  control_mode="Manuell",modifiers=("reset-on-loss",))


def test_fresh_cross_opens_only_legal_amount():
    a=avoid_loss_macd_entry_v1(
        current_target=TargetInventoryV3(0),observation=observation(2,2),
        previous_observation=observation(-1,0),bars=bars())
    assert a.action=="OPEN_MACD_CROSS"
    assert a.target.amount==.01
    b=avoid_loss_macd_entry_v1(
        current_target=TargetInventoryV3(0),observation=observation(-2,2),
        previous_observation=observation(1,0),bars=bars())
    assert b.target.amount==-.01


def test_nonflat_never_pyramids_and_does_not_flip_on_opposite_macd():
    r=avoid_loss_macd_entry_v1(
        current_target=TargetInventoryV3(.01),
        observation=observation(-3,4),
        previous_observation=observation(1,2),bars=bars())
    assert r.target.amount==.01
    assert r.action=="HOLD_UNTIL_MARGIN_STOP"


def test_low_volatility_does_not_enter_even_with_cross():
    quiet=tuple(SimpleNamespace(open=100,high=100.00001,
                low=99.99999,close=100) for _ in range(16))
    r=avoid_loss_macd_entry_v1(
        current_target=TargetInventoryV3(0),
        observation=observation(2,2),
        previous_observation=observation(-1,0),bars=quiet)
    assert r.action=="FLAT_TOO_LITTLE_MOVEMENT"
    assert r.target.amount==0


def test_first_bar_bootstraps_without_open():
    r=avoid_loss_macd_entry_v1(
        current_target=TargetInventoryV3(0),
        observation=observation(1,2),
        previous_observation=None,bars=bars())
    assert r.action=="HOLD_BOOTSTRAP"
    assert r.target.amount==0


def test_durable_stage_requires_matched_reconciled_order(tmp_path):
    db=str(tmp_path/"margin.sqlite")
    reserve(request_key="R-1",trader_id="alpha",account_id="NOK-1",
            uic=4912,asset_type="CfdOnIndex",expected_inventory=.01,
            submitted_amount=.01,submitted_side="Buy",db_path=db)
    stage_entry_preflight_v1(
        trader_id="alpha",request_key="R-1",margin_nok=1000,
        account_id="NOK-1",uic=4912,asset_type="CfdOnIndex",
        signed_amount=.01,db_path=db)
    assert staged_entry_for_reconciled_order_v1(
        trader_id="alpha",account_id="NOK-1",uic=4912,
        asset_type="CfdOnIndex",db_path=db) is None
    mark(request_key="R-1",state="RECONCILED",
         broker_order_id="SAXO-1",db_path=db)
    d=staged_entry_for_reconciled_order_v1(
        trader_id="alpha",account_id="NOK-1",uic=4912,
        asset_type="CfdOnIndex",db_path=db)
    assert d["initial_margin_nok"]==1000
    assert d["broker_order_id"]=="SAXO-1"
    assert staged_entry_for_reconciled_order_v1(
        trader_id="beta",account_id="NOK-1",uic=4912,
        asset_type="CfdOnIndex",db_path=db) is None
    pos=ConfirmedPositionV1("NOK-1",4912,"CfdOnIndex","P-1",.01,1000)
    register_confirmed_entry_anchor_v1(
        trader_id="alpha",position=pos,
        reconciled_open_request_key="R-1",confirmed_order_id="SAXO-1",
        confirmed_at=T0,db_path=db)
    with pytest.raises(ValueError):
        stage_entry_preflight_v1(
            trader_id="alpha",request_key="R-1",margin_nok=400,
            account_id="NOK-1",uic=4912,asset_type="CfdOnIndex",
            signed_amount=.01,db_path=db)
    with pytest.raises(ValueError):
        retire_confirmed_flat_v1(trader_id="alpha",
            broker_exact_flat=False,db_path=db)
    assert retire_confirmed_flat_v1(trader_id="alpha",
           broker_exact_flat=True,db_path=db)
    assert staged_entry_for_reconciled_order_v1(
        trader_id="alpha",account_id="NOK-1",uic=4912,
        asset_type="CfdOnIndex",db_path=db) is None


def test_exit_bar_latch_monotone_and_restart_safe(tmp_path):
    db=str(tmp_path/"signals.sqlite")
    save_avoid_loss_exit_bar_v1(trader_id="pilot",at=T0,db_path=db)
    save_avoid_loss_exit_bar_v1(trader_id="pilot",
        at=T0-timedelta(minutes=2),db_path=db)
    assert load_avoid_loss_exit_bar_v1(
        trader_id="pilot",db_path=db)==T0
    save_avoid_loss_exit_bar_v1(trader_id="pilot",
        at=T0+timedelta(minutes=2),db_path=db)
    assert load_avoid_loss_exit_bar_v1(
        trader_id="pilot",db_path=db)==T0+timedelta(minutes=2)


def test_stop_is_not_paper_heuristic():
    src=Path("autotrader_v3_avoid_loss_strategy_v1.py").read_text()
    assert "Risk observer" in src
    assert "SaxoOrderRequest" not in src
    assert "place_order(" not in src
