"""End-to-end contract for opt-in V3 LIVE whipsaw/volatility safety overlays."""
from datetime import datetime,timedelta,timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from autotrader_v3_domain import TargetInventoryV3
from autotrader_v3_whipsaw_live_v1 import (
    WhipsawEvidenceV3,WhipsawLiveModifierV3,VolatilityPauseLiveModifierV3,
    evaluate_whipsaw_live_v3,assess_volatility_live_v3,
    is_whipsaw_live_approved_v3,set_whipsaw_live_approval_v3,
)
from autotrader_v3_registry_v1 import live_config_issues_v3, LIVE_MODIFIERS_V3

BASE=datetime(2026,10,13,6,0,tzinfo=timezone.utc)


def bar(i,close):
    return SimpleNamespace(bar_time=(BASE+timedelta(minutes=i)).isoformat(),
                           close=float(close))


def zigzag_bars(count=37):
    return [bar(i,30000+(12 if i%2 else 0)) for i in range(count)]


def decide(filter_,desired):
    return filter_.apply(None,TargetInventoryV3(desired))


def test_separate_live_approval_defaults_off_is_per_instance_and_revocable(tmp_path):
    db=str(tmp_path/"whip.db")
    assert is_whipsaw_live_approved_v3("tech100-a",db_path=db) is False
    assert is_whipsaw_live_approved_v3("tech100-b",db_path=db) is False
    assert set_whipsaw_live_approval_v3("tech100-a",True,db_path=db)
    assert is_whipsaw_live_approved_v3("tech100-a",db_path=db)
    assert not is_whipsaw_live_approved_v3("tech100-b",db_path=db)
    assert set_whipsaw_live_approval_v3("tech100-a",False,db_path=db) is False
    assert not is_whipsaw_live_approved_v3("tech100-a",db_path=db)


def test_all_runtime_ready_v3_strategies_accept_safety_modifiers():
    assert {"whipsaw","volatility-pause"}.issubset(set(LIVE_MODIFIERS_V3))
    for key in ("macd","macd-histogram","macd-stoch-v2",
                "aen21-sticky-fast-exit"):
        assert live_config_issues_v3(
            strategy_key=key,timeframe="10m",regime_timeframe="30m",
            control_mode="Manuell",
            modifiers=("whipsaw","volatility-pause"))==()


def test_whipsaw_detector_uses_closed_1m_data_and_durable_hysteresis(tmp_path):
    db=str(tmp_path/"w.db")
    bars=zigzag_bars(37)
    now=BASE+timedelta(minutes=37,seconds=1)
    e=evaluate_whipsaw_live_v3(
        trader_id="a",bars=bars,now=now,db_path=db)
    assert e.data_ok and e.active and e.changes>=7
    assert e.efficiency<0.35
    assert e.last_bar_time==bars[-1].bar_time
    again=evaluate_whipsaw_live_v3(
        trader_id="a",bars=bars,now=now,db_path=db)
    assert again.quiet_bars==0 and again.active
    # Incoming signal with an old/replayed bar cannot clear detector.
    old=evaluate_whipsaw_live_v3(
        trader_id="a",bars=bars[:-1],
        now=BASE+timedelta(minutes=36,seconds=1),db_path=db)
    assert old.data_ok is False
    assert old.active is True
    extended=list(bars)
    # Clear out all zigzag returns, then require 3 quiet distinct closed bars.
    for i in range(37,53):
        extended.append(bar(i,30000+0.5*(i-36)))
        e=evaluate_whipsaw_live_v3(
            trader_id="a",bars=extended,
            now=BASE+timedelta(minutes=i+1,seconds=1),db_path=db)
    assert e.data_ok and not e.active


def test_gaps_missing_freshness_and_unsafe_config_fail_closed(tmp_path):
    db=str(tmp_path/"fail.db")
    bars=zigzag_bars()
    gap=bars[:12]+bars[13:]
    no=evaluate_whipsaw_live_v3(
        trader_id="b",bars=gap,now=BASE+timedelta(minutes=37),
        db_path=db)
    assert not no.data_ok
    stale=evaluate_whipsaw_live_v3(
        trader_id="b",bars=bars,now=BASE+timedelta(minutes=45),
        db_path=db)
    assert not stale.data_ok
    with pytest.raises(ValueError):
        evaluate_whipsaw_live_v3(
            trader_id="b",bars=bars,now=BASE+timedelta(minutes=37),
            lookback_bars=0,db_path=db)


def test_pause_blocks_adds_and_entries_but_not_reductions_exits(tmp_path):
    for data_ok,active in ((True,True),(False,False)):
        evidence=WhipsawEvidenceV3(
            active=active,data_ok=data_ok,last_bar_time=None,
            changes=9,efficiency=0.1,quiet_bars=0,reason="test")
        held=WhipsawLiveModifierV3(actual_inventory=0.02,evidence=evidence)
        assert decide(held,0.04)[0].amount==pytest.approx(0.02)
        assert decide(held,0.01)[0].amount==pytest.approx(0.01)
        assert decide(held,0.0)[0].amount==0
        assert decide(held,-0.01)[0].amount==0
        empty=WhipsawLiveModifierV3(actual_inventory=0,evidence=evidence)
        assert decide(empty,-0.01)[0].amount==0
    good=WhipsawLiveModifierV3(
        actual_inventory=0.02,
        evidence=WhipsawEvidenceV3(False,True,None,0,0.8,0,"clear"))
    assert decide(good,0.04)[0].amount==pytest.approx(0.04)


def test_volatility_pause_matches_lab_high_vol_proxy():
    calm=[bar(i,30000+i*.002) for i in range(61)]
    ok,high=assess_volatility_live_v3(
        bars=calm,now=BASE+timedelta(minutes=61))
    assert ok and not high
    spiky=[bar(i,30000+i*.002) for i in range(49)]
    for i in range(49,61):
        spiky.append(bar(i,30000+(18 if i%2 else -18)))
    ok,high=assess_volatility_live_v3(
        bars=spiky,now=BASE+timedelta(minutes=61))
    assert ok and high
    assert not assess_volatility_live_v3(
        bars=spiky[:45]+spiky[46:],now=BASE+timedelta(minutes=61))[0]
    mod=VolatilityPauseLiveModifierV3(
        actual_inventory=-0.02,data_ok=True,high_vol=True)
    assert decide(mod,-0.03)[0].amount==pytest.approx(-0.02)
    assert decide(mod,-0.01)[0].amount==pytest.approx(-0.01)
    assert decide(mod,0.02)[0].amount==0
    assert decide(mod,0)[0].amount==0


def test_live_runtime_is_fail_closed_and_ui_requires_manual_opt_in():
    root=Path(__file__).resolve().parent.parent
    runtime=(root/"autotrader_v3_live_runtime_v1.py").read_text()
    ui=(root/"autotrader_v3_instance_controls_ui_v1.py").read_text()
    assert "if 'whipsaw' in config.modifiers" in runtime
    assert "is_whipsaw_live_approved_v3(e.pilot_key" in runtime
    assert "VolatilityPauseLiveModifierV3(" in runtime
    assert "closed_bars_v2(" in runtime
    assert "align_closed_bar_target_v3(" in runtime
    assert "Godkjenn Whipsaw Detector for LIVE" in ui
    assert "Tilbakekall Whipsaw LIVE-godkjenning" in ui
    assert "set_whipsaw_live_approval_v3(trader_id,True)" in ui
    assert "Forhåndsvelg Fast Exit S10/R30 + Volatility Pause" in ui
    # Selecting the research-inspired preset is not order placement.
    assert "place_order(" not in ui
