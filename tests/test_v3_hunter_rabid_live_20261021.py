"""Causal Hunter/Rabid V3 LIVE tick gating, persistence, and order boundaries."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from pathlib import Path

import pytest

from autotrader_v3_tick_shadow_live_v1 import (
    HUNTER_CATALOG_KEY,DOG_CATALOG_KEY,TICK_RUNTIME_KEYS,
    BROKER_ORDERS_PER_HOUR,evaluate_tick_live_v3,
)
from autotrader_v3_registry_v1 import live_config_issues_v3,sim_config_issues_v3,strategy_v3
from autotrader_v3_strategy_registry_v1 import strategy_adapter_v3
from autotrader_v3_strategy_sizing_v1 import strategy_amount_config_v3
from autotrader_v3_order_guard_v1 import ensure_schema as ensure_order_guard
from live_sim_hyper_quotes_v1 import HyperQuoteRecorder
from database import connect

START=datetime(2026,10,21,15,0,tzinfo=timezone.utc)


def make_db(tmp_path):
    db=str(tmp_path/"ticks.db")
    rec=HyperQuoteRecorder(db)
    ensure_order_guard(db)
    return db,rec


def put(rec,second,mid,*,uic=4912,spread=1.):
    at=START+timedelta(seconds=second)
    return rec.observe(SimpleNamespace(
        market="US Tech 100 NAS",uic=uic,
        asset_type="CfdOnIndex",bid=mid-spread/2,ask=mid+spread/2,
        observed_at=at),tradable=True,now=at)


def run(db,second,key,*,actual=0.,trader="pilot",uic=4912,changed=False,asset="CfdOnIndex"):
    return evaluate_tick_live_v3(
        trader_id=trader,strategy_key=key,account_uic=uic,asset_type=asset,
        actual_amount=actual,tranche=.01,context_changed=changed,
        db_path=db,now=START+timedelta(seconds=second))


@pytest.mark.parametrize("key",[HUNTER_CATALOG_KEY,DOG_CATALOG_KEY])
def test_fresh_quote_and_restart_safe_live_target(tmp_path,key):
    db,rec=make_db(tmp_path)
    put(rec,0,30000)
    initial=run(db,0,key)
    assert initial.decision.action=="BOOTSTRAP"
    assert initial.decision.target.amount==0
    put(rec,1,30012)
    opened=run(db,1,key)
    assert opened.decision.target.amount==.01
    assert opened.decision.action=="TICK_LONG"
    # Across new code objects/process restarts, state in Postgres is authoritative.
    put(rec,2,30017)
    resumed=run(db,2,key,actual=.01)
    assert resumed.decision.target.amount==.01
    assert resumed.decision.action=="HOLD_LONG"
    assert "Saxo BBO" in resumed.decision.reason


@pytest.mark.parametrize("key",[HUNTER_CATALOG_KEY,DOG_CATALOG_KEY])
def test_exact_uic_stale_and_strategy_change_fail_closed(tmp_path,key):
    db,rec=make_db(tmp_path)
    put(rec,0,30000,uic=4912)
    assert run(db,0,key,uic=777).decision.action=="BLOCK_PRODUCT"
    assert run(db,0,key,asset="FxSpot").decision.action=="BLOCK_PRODUCT"
    run(db,0,key)
    for sec in range(1,3):
        put(rec,sec,30000+12*sec,uic=777)
    assert run(db,2,key).decision.action=="WAIT_QUOTES"
    assert run(db,20,key).decision.action=="WAIT_QUOTES"
    put(rec,21,30030)
    switched=run(db,21,key,actual=.01,changed=True)
    assert switched.decision.action=="BOOTSTRAP"
    assert switched.decision.target.amount==.01


def test_hunter_exits_on_retrace_with_no_broker_netting(tmp_path):
    db,rec=make_db(tmp_path)
    for second,mid in [(0,30000),(1,30012),(2,30020),(3,30020),
                       (4,30017),(5,30016)]:
        put(rec,second,mid)
        result=run(db,second,HUNTER_CATALOG_KEY,
                   actual=(0 if second<=1 else .01))
    assert result.decision.target.amount==0
    assert result.decision.action=="TICK_FLAT"
    assert "IMPULSE_EXHAUSTED" in result.decision.reason


def test_rabid_reversal_is_target_only_and_broker_owns_split(tmp_path):
    db,rec=make_db(tmp_path)
    targets=[]
    for second,mid in [(0,30000),(1,30004),(2,30010),(3,30008),(4,30003)]:
        put(rec,second,mid)
        result=run(db,second,DOG_CATALOG_KEY,
                   actual=(.01 if second>=2 else 0))
        targets.append(result.decision.target.amount)
    assert targets[1]==.01
    assert targets[4]==-.01
    runtime=Path("autotrader_v3_live_runtime_v1.py").read_text()
    assert "pending_order_v3(" in runtime
    assert "reconcile_position_v3(" in runtime
    assert "broker.precheck(order)" in runtime
    assert "reserve_order_v3(" in runtime
    assert "broker.place_order(order,confirm_live=True)" in runtime
    tick_src=Path("autotrader_v3_tick_shadow_live_v1.py").read_text()
    for forbidden in ("place_order(", "SaxoOrderRequest(", "set_live_enabled_v3("):
        assert forbidden not in tick_src


def test_hourly_durable_broker_budget_blocks_new_exposure_but_not_close(tmp_path):
    db,rec=make_db(tmp_path)
    with connect(db) as conn:
        for i in range(BROKER_ORDERS_PER_HOUR-1):
            conn.execute("""INSERT INTO autotrader_v3_order_guard(
                request_key,trader_id,account_id,uic,asset_type,state,updated_at)
                VALUES(?,?,?,?,?,'RECONCILED',?)""",
                (str(i),"pilot","account",4912,"CfdOnIndex",
                 START.strftime("%Y-%m-%d %H:%M:%S")))
    put(rec,0,30000)
    run(db,0,HUNTER_CATALOG_KEY)
    put(rec,1,30012)
    blocked=run(db,1,HUNTER_CATALOG_KEY)
    assert blocked.decision.action=="WAIT_BROKER_QUOTA"
    assert blocked.decision.target.amount==0
    # Exit is risk-reducing and may be performed even at complete capacity.
    with connect(db) as conn:
        conn.execute("""INSERT INTO autotrader_v3_order_guard(
            request_key,trader_id,account_id,uic,asset_type,state,updated_at)
            VALUES(?,?,?,?,?,'SUBMITTED',?)""",("last","pilot","account",4912,
              "CfdOnIndex",START.strftime("%Y-%m-%d %H:%M:%S")))
    run(db,2,HUNTER_CATALOG_KEY,actual=.01,changed=True) if put(rec,2,30012) else None
    for second,mid in [(3,30021),(4,30018),(5,30017),(6,30016)]:
        put(rec,second,mid)
        close=run(db,second,HUNTER_CATALOG_KEY,actual=.01)
    assert close.decision.target.amount==0


def test_data_gap_never_replays_previous_open_signal(tmp_path):
    db,rec=make_db(tmp_path)
    put(rec,0,30000)
    run(db,0,HUNTER_CATALOG_KEY)
    put(rec,1,30012)
    assert run(db,1,HUNTER_CATALOG_KEY).decision.target.amount==.01
    put(rec,20,30015)
    gap=run(db,20,HUNTER_CATALOG_KEY,actual=0)
    assert gap.decision.target.amount==0
    assert gap.decision.action in ("HOLD_FLAT","WAIT_GAP")


def test_catalog_controls_and_quote_only_worker_gating():
    assert len(TICK_RUNTIME_KEYS)==2
    for key in (HUNTER_CATALOG_KEY,DOG_CATALOG_KEY):
        spec=strategy_v3(key)
        assert spec.runtime_ready
        assert strategy_adapter_v3(spec.runtime_key).live_route_enabled
        assert not live_config_issues_v3(strategy_key=key,timeframe="1m",
            control_mode="Manuell",modifiers=())
        assert live_config_issues_v3(strategy_key=key,timeframe="5m",
            control_mode="Manuell",modifiers=())
        assert sim_config_issues_v3(strategy_key=key,timeframe="1m",
            control_mode="Manuell",modifiers=())
    source=Path("autotrader_v3_live_runtime_v1.py").read_text()
    assert "elif e.strategy_key in TICK_RUNTIME_KEYS" in source
    assert "hyper_quote_only=True" in Path("worker.py").read_text()
    assert "TICK_CATALOG_KEYS" in Path("autotrader_v3_hyper_chase_live_v1.py").read_text()
