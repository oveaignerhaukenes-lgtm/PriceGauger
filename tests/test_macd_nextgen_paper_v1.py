"""NextGen MACD must be semantically consistent, causal and PAPER-only."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import macd_nextgen_paper_v1 as mod
from macd_nextgen_paper_v1 import MacdConfig, PolicyState, decide, replay


def test_pyramid_opposite_sign_flattens_entire_inventory_before_reentry():
    config=MacdConfig(minutes=5,flip=True,hold_before_flip=True,pyramide=True,max_tranches=5)
    result=decide(config,PolicyState(target=1.0),spread=-0.2,
                  previous_spread=0.1,contiguous=True)
    assert result.state.target == 0.0
    assert result.state.pending_reentry == -1
    assert result.reason == "OPPOSITE_REGIME_FULL_FLAT"
    resumed=decide(config,result.state,spread=-0.3,previous_spread=-0.2,
                   contiguous=True)
    assert resumed.state.target == pytest.approx(-0.2)
    assert resumed.reason == "REBUILD_AFTER_FLAT"


def test_pyramid_full_flat_even_when_opposing_cross_was_missed():
    config=MacdConfig(minutes=2,pyramide=True,flip=True)
    out=decide(config,PolicyState(target=-0.8),spread=0.1,
               previous_spread=-0.5,contiguous=False)
    assert out.state.target == 0
    # Reentry isn't allowed without a subsequent contiguous completed observation.
    blocked=decide(config,out.state,spread=0.2,previous_spread=0.1,contiguous=False)
    assert blocked.state.target==0


def test_hold_and_flip_are_different_from_trailing():
    hold=MacdConfig(minutes=2,flip=True,hold_before_flip=True)
    quiet=decide(hold,PolicyState(target=1),spread=0.05,
                 previous_spread=0.12,contiguous=True)
    assert quiet.state.target==1
    reverse=decide(hold,quiet.state,spread=-0.1,
                   previous_spread=0.05,contiguous=True)
    assert reverse.state.target==-1
    assert reverse.reason=="FLIP_ON_CROSS"
    trail=MacdConfig(minutes=2,flip=True,hold_before_flip=False,trailing=True)
    shrink=decide(trail,PolicyState(target=1),spread=0.05,
                  previous_spread=0.12,contiguous=True)
    assert shrink.state.target==pytest.approx(0.8)


def test_no_flip_closes_only_and_waits_for_new_cross():
    config=MacdConfig(minutes=2,flip=False)
    exited=decide(config,PolicyState(target=1),spread=-.1,
                  previous_spread=.1,contiguous=True)
    assert exited.state.target==0
    wait=decide(config,exited.state,spread=-.2,previous_spread=-.1,contiguous=True)
    assert wait.state.target==0
    new=decide(config,wait.state,spread=.1,previous_spread=-.2,contiguous=True)
    assert new.state.target==1


def test_invalid_mode_pair_is_rejected():
    with pytest.raises(ValueError,match="mutually exclusive"):
        MacdConfig(hold_before_flip=True,trailing=True)


def _bar(minute,price=100.0,open_price=None):
    at=datetime(2026,10,13,tzinfo=timezone.utc)+timedelta(minutes=minute)
    return SimpleNamespace(bar_time=at.isoformat(),market_name="US Tech 100 NAS",
                           open=price if open_price is None else open_price,
                           close=price,high=max(price,price if open_price is None else open_price),
                           low=min(price,price if open_price is None else open_price))


def _obs(minute,spread):
    at=datetime(2026,10,13,tzinfo=timezone.utc)+timedelta(minutes=minute)
    return SimpleNamespace(closed_at=at,spread=spread)


def test_fee_assumption_charges_both_sides_on_full_reversal(monkeypatch):
    start=datetime(2026,10,13,tzinfo=timezone.utc)
    monkeypatch.setattr(mod,"_observations",lambda _bars,_tf:{
        start+timedelta(minutes=1):_obs(1,-.2),
        start+timedelta(minutes=2):_obs(2,.2),
        start+timedelta(minutes=3):_obs(3,-.2)})
    bars=[_bar(i) for i in range(5)]
    cfg=MacdConfig(minutes=1)
    r=replay(cfg,bars,started_at=start,costs_enabled=True,
             commission_side_bps=8,quoted_spread_bps=2)
    assert r.executions==2
    # Entry = 1 broker order, full reversal = close + open.
    assert r.estimated_broker_orders==3
    assert r.gross_pct==pytest.approx(0)
    assert r.return_pct < -0.25
    assert r.return_pct > -0.28
    assert r.total_cost_pct > 0.25
    zero=replay(cfg,bars,started_at=start,costs_enabled=False,
                commission_side_bps=8,quoted_spread_bps=2)
    assert zero.return_pct==pytest.approx(0)
    assert zero.executions==r.executions


def test_decision_cannot_capture_its_own_signal_candle_profit(monkeypatch):
    start=datetime(2026,10,13,tzinfo=timezone.utc)
    monkeypatch.setattr(mod,"_observations",lambda _bars,_tf:{
        start+timedelta(minutes=1):_obs(1,-.2),
        start+timedelta(minutes=2):_obs(2,.2)})
    # The large positive candle at minute 1 triggers CROSS_UP only at its end.
    bars=[_bar(0,100),_bar(1,110,100),_bar(2,110),_bar(3,110)]
    r=replay(MacdConfig(minutes=1),bars,started_at=start,
             costs_enabled=False)
    assert r.gross_pct==pytest.approx(0)
    assert r.executions==1


def test_new_family_ui_isolated_from_legacy_and_readonly():
    page=Path("pages/0_Live_Sim_Lab.py").read_text(encoding="utf-8")
    frontend=Path("macd_nextgen_lab_ui_v1.py").read_text(encoding="utf-8")
    engine=Path("macd_nextgen_paper_v1.py").read_text(encoding="utf-8")
    assert '("AEn Core · Adaptive Engine","Nye strategier · MACD","V2 strategies","Legacy strategies")' in page
    assert "render_nextgen_macd_lab_v1()" in page
    assert "st.stop()" in page
    for title in ("Flip","Hold before flip","Pyramide","Trailing",
                  "Inkluder kostnader","Spread","macd"):
        assert title.lower() in frontend.lower()
    assert "host.addEventListener('dblclick'" in frontend
    assert "chart.subscribeCrosshairMove" in frontend
    assert "grid-template-columns:minmax(0,1fr) 245px" in frontend
    assert "reports.sort(key=" in frontend
    assert "configured_client" not in engine
    assert "place_order" not in engine
    assert "from database import" not in engine


def test_no_semantic_conversion_of_legacy_macd_flip_to_trailing():
    from autotrader_v3_registry_v1 import migrate_legacy_strategy_v3, strategy_v3
    for minutes in (1,2,5,15):
        assert migrate_legacy_strategy_v3(
            "macd-%dm-flip-control-shadow-v1" % minutes
        ) is None
    spec=strategy_v3("macd")
    assert "Trailing" in spec.label
    assert spec.runtime_key=="macd-trailing-v1"
    selector=Path("autotrader_v3_instance_controls_ui_v1.py").read_text(encoding="utf-8")
    assert "'Legacy strategies', keys" in selector
