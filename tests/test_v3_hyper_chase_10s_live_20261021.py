"""HyperChase 10s V3 LIVE quote freshness, target reversal, and no blind order."""
from datetime import datetime,timedelta,timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from live_sim_hyper_quotes_v1 import HyperQuoteRecorder
from autotrader_v3_hyper_chase_live_v1 import (
    FAST_CATALOG_KEY,FILTERED_CATALOG_KEY,FAST_RUNTIME_KEY,
    HYPER_RUNTIME_KEYS,evaluate_hyper_chase_live_v3,
    evaluate_hyper_closed_bar_compat_v3,live_hyper_quote_cursors_v3,
)
from autotrader_v3_registry_v1 import live_config_issues_v3,sim_config_issues_v3,strategy_v3
from autotrader_v3_strategy_registry_v1 import strategy_adapter_v3
from autotrader_v3_strategy_sizing_v1 import strategy_amount_config_v3

START=datetime(2026,10,21,15,0,tzinfo=timezone.utc)


def add_quote(recorder,sec,price,*,uic=4912):
    at=START+timedelta(seconds=sec)
    return recorder.observe(
        SimpleNamespace(market="US Tech100 NAS",uic=uic,
            asset_type="CfdOnIndex",bid=price-1.,ask=price+1.,
            observed_at=at),
        tradable=True,now=at)


def evaluate(db,sec,*,actual=0.,key=FAST_CATALOG_KEY,
             uic=4912,changed=False,trader="test"):
    return evaluate_hyper_chase_live_v3(
        trader_id=trader,strategy_key=key,account_uic=uic,
        actual_amount=actual,tranche=.01,
        context_changed=changed,db_path=db,
        now=START+timedelta(seconds=sec))


@pytest.mark.parametrize("key",(FAST_CATALOG_KEY,FILTERED_CATALOG_KEY))
def test_live_10s_pulse_then_immediate_opposite_target_no_cooldown(tmp_path,key):
    db=str(tmp_path/"live-quote.db")
    recorder=HyperQuoteRecorder(db)
    add_quote(recorder,0,30000.)
    boot=evaluate(db,0,key=key)
    assert boot.decision.target.amount==0.
    assert boot.decision.action=="BOOTSTRAP"
    for sec in range(1,12):
        assert add_quote(recorder,sec,30000+4*sec)
    long=evaluate(db,11,key=key)
    assert long.decision.target.amount==.01
    assert long.decision.action=="CHASE_LONG"
    # Quote reversal creates a direct SHORT target even if Saxo holds LONG.
    # The existing executor enforces CLOSE and reconciliation first.
    for sec in range(12,30):
        assert add_quote(recorder,sec,30044-6*(sec-11))
    short=evaluate(db,29,actual=.01,key=key)
    assert short.decision.target.amount==-.01
    assert short.decision.action=="CHASE_SHORT"
    assert "quote10" in short.decision_key
    assert short.decision_key!=long.decision_key
    assert short.decision.target.amount*long.decision.target.amount<0


def test_quote_quality_and_uic_gate_fail_closed(tmp_path):
    db=str(tmp_path/"quality.db")
    rec=HyperQuoteRecorder(db)
    add_quote(rec,0,30000)
    evaluate(db,0)
    for sec in range(1,12):
        add_quote(rec,sec,30000+4*sec,uic=9912)
    foreign=evaluate(db,11)
    assert foreign.decision.action=="NEED_QUOTES"
    assert foreign.decision.target.amount==0
    for sec in range(1,12):
        add_quote(rec,sec,30000+4*sec,uic=4912)
    stale=evaluate(db,20,actual=-.01)
    assert stale.decision.action=="STALE_QUOTES"
    assert stale.decision.target.amount==-.01
    good=evaluate(db,11)
    assert good.decision.action=="CHASE_LONG"


def test_bootstrap_context_switch_requires_new_live_warmup(tmp_path):
    db=str(tmp_path/"bootstrap.db")
    rec=HyperQuoteRecorder(db)
    for sec in range(12):
        add_quote(rec,sec,30000+4*sec)
    first=evaluate(db,11,actual=.01)
    assert first.decision.action=="BOOTSTRAP"
    second=evaluate(db,12,actual=.01)
    assert second.decision.action=="WAIT_WARMUP"
    reset=evaluate(db,21,changed=True,actual=.01)
    assert reset.decision.action=="BOOTSTRAP"


def test_strategies_are_real_live_routes_with_paper_only_v3_sim():
    assert len(HYPER_RUNTIME_KEYS)==2
    for key in (FAST_CATALOG_KEY,FILTERED_CATALOG_KEY):
        spec=strategy_v3(key)
        assert spec.runtime_ready
        assert strategy_adapter_v3(spec.runtime_key).live_route_enabled
        assert live_config_issues_v3(
            strategy_key=key,timeframe="1m",control_mode="Manuell",
            modifiers=())==()
        assert any("requires 1m" in issue for issue in live_config_issues_v3(
            strategy_key=key,timeframe="5m",control_mode="Manuell",
            modifiers=()))
        assert any("PAPER" in issue for issue in sim_config_issues_v3(
            strategy_key=key,timeframe="1m",control_mode="Manuell",
            modifiers=()))
    probe=evaluate_hyper_closed_bar_compat_v3(
        trader_id="generic",observation=None,strategy_key=FAST_RUNTIME_KEY,
        actual_inventory=None)
    assert probe.decision.target.amount==0


def test_broker_side_always_v3_reconcile_first_and_no_auto_activation():
    runtime=Path("autotrader_v3_live_runtime_v1.py").read_text()
    watcher=Path("worker.py").read_text()
    ui=Path("autotrader_v3_instance_controls_ui_v1.py").read_text()
    module=Path("autotrader_v3_hyper_chase_live_v1.py").read_text()
    assert "evaluate_hyper_chase_live_v3(" in runtime
    assert "hyper_quote_only" in runtime
    assert "if quote_changed and not (changed or heartbeat)" in watcher
    assert "live_hyper_quote_cursors_v3" in watcher
    assert "pending_order_v3(" in runtime
    assert "reconcile_position_v3(" in runtime
    assert "reserve_order_v3(" in runtime
    assert "broker.precheck(order)" in runtime
    assert "broker.place_order(order,confirm_live=True)" in runtime
    assert "10s" in ui
    for forbidden in ("place_order(","SaxoOrderRequest(",
                      "set_live_enabled_v3(","save_autotrader_config_v3("):
        assert forbidden not in module


def test_quote_cursor_requires_live_ownership_and_arming(tmp_path):
    # Missing enrolled LIVE instance must yield no quote-triggered orders.
    assert live_hyper_quote_cursors_v3(
        db_path=str(tmp_path/"no-armed-instance.db"),now=START)==()
