"""Avoid Loss V1: 1% frozen margin stop, 2% activation and 10% peak giveback.

These are broker-margin-NAV percentages, NOT underlying index percentages.
No test invokes LIVE Saxo or mutates a user's LIVE instance.
"""
from datetime import datetime,timedelta,timezone
from dataclasses import replace
from pathlib import Path

import pytest

from autotrader_v3_avoid_loss_v1 import (
    AvoidLossSettingsV1, ConfirmedPositionV1, BrokerPnLSampleV1,
    AvoidLossStateV1, AvoidLossEntrySignalV1, AvoidLossReentryV1,
    inspect_open_position_v1, evaluate_flat_entry_v1,
)

T0=datetime(2026,10,16,12,0,tzinfo=timezone.utc)
POSITION=ConfirmedPositionV1(
    account_id="autotrader",uic=12345,asset_type="CfdOnIndex",
    position_token="saxo-confirmed-entry-1",signed_amount=.01,
    entry_margin_nok=1000.0,
)


def sample(pnl_nok,now=T0,position=POSITION,**changes):
    return BrokerPnLSampleV1(
        position_key=changes.pop("position_key",position.key),
        mark_to_liquidate_nok=pnl_nok,
        currency=changes.pop("currency","NOK"),
        as_of=changes.pop("as_of",now),
        reliability=changes.pop("reliability","Ok"),
        quote_delay_minutes=changes.pop("quote_delay_minutes",0),
        has_verified_costs=changes.pop("has_verified_costs",True),
        **changes,
    )


def observe(pnl,state=None,at=T0,position=POSITION,**sample_changes):
    return inspect_open_position_v1(
        position=position,sample=sample(pnl,at,position=position,**sample_changes),
        state=state,now=at,
    )


def test_margin_not_underlying_index_price_is_percentage_denominator():
    result=observe(-9.99)
    assert result.action=="HOLD"
    assert result.pnl_pct==pytest.approx(-.999)
    stopped=observe(-10.0)
    assert stopped.action=="REQUEST_CLOSE"
    assert stopped.reason=="LOSS_STOP"
    assert stopped.pnl_pct==-1
    assert stopped.state.exit_pending
    assert stopped.floor_pct is None


def test_activation_and_giveback_from_20_to_18_nok():
    start=observe(0)
    result=observe(20,start.state,at=T0+timedelta(seconds=1))
    assert result.action=="HOLD"
    assert result.peak_pct==pytest.approx(2.0)
    assert result.floor_pct==pytest.approx(1.8)
    just_above=observe(18.01,result.state,at=T0+timedelta(seconds=2))
    assert just_above.action=="HOLD"
    triggered=observe(18,just_above.state,at=T0+timedelta(seconds=3))
    assert triggered.action=="REQUEST_CLOSE"
    assert triggered.reason=="PEAK_GIVEBACK"
    assert triggered.floor_pct==pytest.approx(1.8)


def test_peak_grows_to_5pct_floor_is_4point5pct():
    a=observe(21)
    b=observe(50,a.state,at=T0+timedelta(seconds=1))
    assert b.peak_pct==5
    assert b.floor_pct==pytest.approx(4.5)
    c=observe(47,b.state,at=T0+timedelta(seconds=2))
    assert c.action=="HOLD"
    d=observe(44.5,c.state,at=T0+timedelta(seconds=3))
    assert d.reason=="PEAK_GIVEBACK"


def test_trailing_floor_never_decreases_during_drawdown():
    a=observe(50)
    b=observe(47,a.state,at=T0+timedelta(seconds=1))
    assert b.state.peak_pct==pytest.approx(5)
    assert b.floor_pct==pytest.approx(4.5)
    c=observe(60,b.state,at=T0+timedelta(seconds=2))
    assert c.peak_pct==pytest.approx(6.0)
    assert c.floor_pct==pytest.approx(5.4)


def test_early_gain_below_activation_has_only_initial_loss_stop():
    a=observe(19)
    assert a.floor_pct is None
    b=observe(1,a.state,at=T0+timedelta(seconds=1))
    assert b.floor_pct is None
    assert b.action=="HOLD"


def test_close_latch_is_sticky_and_does_not_retry_or_open_reverse():
    close=observe(-12)
    later=observe(100,close.state,at=T0+timedelta(seconds=1))
    assert later.action=="WAIT_RECONCILE"
    assert later.state.exit_pending
    assert later.state.exit_reason=="LOSS_STOP"


def test_position_mutation_must_reanchor_margin_and_peak():
    first=observe(30)
    changed=replace(POSITION,signed_amount=.02)
    denied=observe(10,first.state,at=T0+timedelta(seconds=1),
                   position=changed)
    assert denied.action=="BLOCKED"
    assert "position changed" in denied.reason
    assert denied.state==first.state


@pytest.mark.parametrize("changes",[
    {"currency":"USD"},
    {"reliability":"Delayed"},
    {"quote_delay_minutes":1},
    {"has_verified_costs":False},
    {"position_key":("wrong","uid","asset","id",.01)},
    {"as_of":T0-timedelta(minutes=1)},
    {"as_of":T0+timedelta(seconds=2)},
])
def test_unreliable_or_stale_broker_samples_do_not_mutate_peak(changes):
    prior=observe(50)
    denied=observe(90,prior.state,at=T0+timedelta(seconds=1),**changes)
    assert denied.action=="BLOCKED"
    assert denied.state==prior.state
    assert denied.pnl_pct is None


def test_non_monotonic_broker_sample_does_not_erase_hwm():
    a=observe(50,at=T0+timedelta(seconds=3))
    old=observe(60,a.state,at=T0+timedelta(seconds=4),
                as_of=T0+timedelta(seconds=2))
    assert old.action=="BLOCKED"
    assert old.state==a.state


@pytest.mark.parametrize("bad_margin", [0,-1,float("nan"),float("inf")])
def test_bad_frozen_margin_rejected(bad_margin):
    with pytest.raises(ValueError):
        replace(POSITION,entry_margin_nok=bad_margin)


def test_breakout_or_fresh_macd_zero_cross_allows_direction_if_room():
    bull=AvoidLossEntrySignalV1(
        confirmed_at=T0,prior_histogram=-.001,histogram=.004,
        breakout_direction=0,expected_opportunity_pct=3.0,
        estimated_round_trip_cost_pct=.2)
    assert evaluate_flat_entry_v1(signal=bull,last_exit=None,now=T0)[0]==1
    bear=replace(bull,prior_histogram=.001,histogram=-.003)
    assert evaluate_flat_entry_v1(signal=bear,last_exit=None,now=T0)[0]==-1
    rising=replace(bull,prior_histogram=.02,histogram=.04,breakout_direction=1)
    assert evaluate_flat_entry_v1(signal=rising,last_exit=None,now=T0)[0]==1
    falling=replace(bear,prior_histogram=-.02,histogram=-.04,breakout_direction=-1)
    assert evaluate_flat_entry_v1(signal=falling,last_exit=None,now=T0)[0]==-1


def test_noise_and_no_acceleration_remain_flat():
    bull=AvoidLossEntrySignalV1(
        confirmed_at=T0,prior_histogram=-.01,histogram=.02,
        breakout_direction=1,expected_opportunity_pct=1.5,
        estimated_round_trip_cost_pct=.2)
    assert evaluate_flat_entry_v1(signal=bull,last_exit=None,now=T0)==(
        0,"FLAT_OPPORTUNITY_TOO_SMALL")
    stalled=replace(bull,prior_histogram=.06,histogram=.04,
                    expected_opportunity_pct=3.0)
    assert evaluate_flat_entry_v1(signal=stalled,last_exit=None,now=T0)==(
        0,"FLAT_NO_DIRECTION")


def test_no_old_same_candle_reentry_after_stopped_out():
    sig=AvoidLossEntrySignalV1(
        confirmed_at=T0,prior_histogram=-.04,histogram=.03,
        breakout_direction=1,expected_opportunity_pct=3.0,
        estimated_round_trip_cost_pct=.2)
    stop=AvoidLossReentryV1(eligible_after=T0,last_closed_direction=1)
    assert evaluate_flat_entry_v1(signal=sig,last_exit=stop,now=T0)==(
        0,"WAIT_NEW_CLOSED_BAR")
    later=replace(sig,confirmed_at=T0+timedelta(minutes=2))
    assert evaluate_flat_entry_v1(
        signal=later,last_exit=stop,now=T0+timedelta(minutes=2))[0]==1
    assert evaluate_flat_entry_v1(
        signal=sig,last_exit=None,now=T0+timedelta(minutes=3))[0]==0


def test_no_runtime_live_broker_authority_in_core():
    src=Path("autotrader_v3_avoid_loss_v1.py").read_text()
    for forbidden in ("SaxoOrderRequest","place_order(", "claim_reserved_for_submission_v3",
        "configured_live_pilot_client_v3","set_live_authority_v3"):
        assert forbidden not in src
