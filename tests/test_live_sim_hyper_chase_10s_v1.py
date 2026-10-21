"""HyperVigilant 10s: actual quotes, next-tick direct flip, two-sided costs."""
from datetime import datetime,timedelta,timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from live_sim_hyper_quotes_v1 import HyperQuoteRecorder
from live_sim_hyper_chase_10s_v1 import (
    ARMS,FAST_MOVE_BPS,VERSION,_track,chase_signal_v1,
    settle_chase_quote_v1,process_chase_cycle_v1,chase_snapshot_v1,
)
from database import connect

START=datetime(2026,10,21,13,0,tzinfo=timezone.utc)


def stamp(sec):
    return (START+timedelta(seconds=sec)).isoformat()


def quote(sec,price):
    return {"quote_at":stamp(sec),"bid":price-1.,"ask":price+1.}


def samples(prices):
    return [(stamp(i),p) for i,p in enumerate(prices)]


@pytest.mark.parametrize("dir",[-1,1])
def test_10s_impulse_detects_reversal_direction_without_macd(dir):
    prices=[30000+dir*i*4 for i in range(11)]
    for arm in ARMS:
        signal,reason,evidence=chase_signal_v1(
            samples(prices),at=stamp(10),bid=prices[-1]-1,
            ask=prices[-1]+1,arm=arm)
        assert signal==dir
        assert reason=="CHASE_10S_IMPULSE"
        assert 9<=evidence["lookback_seconds"]<=10
        assert evidence["threshold_bps"]>0


def test_missing_real_quotes_or_stale_spread_must_not_chase():
    prices=samples([30000+i*4 for i in range(11)])
    assert chase_signal_v1(prices[-6:],at=stamp(10),bid=30039,ask=30041,
                           arm=ARMS[0])[0]==0
    assert chase_signal_v1(
        prices,at=stamp(10),bid=30000,ask=30090,arm=ARMS[0])[1]=="WIDE_SPREAD"
    gap=[prices[i] for i in (0,1,2,3,7,8,9,10)]
    assert chase_signal_v1(gap,at=stamp(10),bid=30039,ask=30041,
                           arm=ARMS[0])[0]==0


def test_chase_only_next_quote_and_no_cooldown_on_direct_flip():
    state=_track(stamp(0),30000.)
    out=[]
    # Constant 1s data, 4 index pts per second => 13.33bp over 10s.
    for sec in range(1,13):
        state,event=settle_chase_quote_v1(
            state,arm=ARMS[0],quote=quote(sec,30000+4*sec),
            now=START+timedelta(seconds=sec))
        out.append(event)
    first_signal=next(i for i,x in enumerate(out)
                      if x["action"]=="CHASE_10S_SIGNAL")
    assert first_signal<=9
    first_open=next(i for i,x in enumerate(out) if x["action"]=="OPEN")
    assert first_open==first_signal+1
    assert out[first_signal]["traded"]==0
    assert out[first_open]["traded"]==1
    assert out[first_open]["signal_delay_seconds"]==pytest.approx(1.)
    assert state["exposure"]==1.
    assert state["entries"]==1
    # Reverse price rapidly, with NO intermediate flat target/quote.
    for sec in range(13,27):
        price=30048-(sec-12)*6
        prior=state["exposure"]
        state,event=settle_chase_quote_v1(
            state,arm=ARMS[0],quote=quote(sec,price),
            now=START+timedelta(seconds=sec))
        out.append(event)
        if event["action"]=="DIRECT_FLIP":
            assert prior==1.
            assert state["exposure"]==-1.
            assert event["turnover"]==pytest.approx(2.)
            assert event["traded"]==1
            assert event["total_cost_nok"]>0
            break
    else:
        pytest.fail("Expected direct flip without a flat quote")
    assert state["flips"]==1
    assert state["trades"]>=2
    assert state["fees_nok"]>0 and state["spread_cost_nok"]>0
    assert state["slippage_nok"]>0
    assert state["last_fill_delay_seconds"]<=3
    assert "cooldown_until" not in state


def test_duplicate_and_gap_cancel_pending_and_no_fictitious_fill():
    state=_track(stamp(0),30000.)
    state["pending"]=1.;state["pending_at"]=stamp(0)
    stale,event=settle_chase_quote_v1(
        state,arm=ARMS[0],quote=quote(8,30100),
        now=START+timedelta(seconds=8))
    assert stale["pending"] is None
    assert stale["exposure"]==0
    assert stale["trades"]==0
    assert stale["gaps"]==1
    assert event["action"]=="FEED_GAP_NO_TRADE"
    duplicate,event2=settle_chase_quote_v1(
        stale,arm=ARMS[0],quote=quote(8,30100),
        now=START+timedelta(seconds=8))
    assert event2 is None and duplicate==stale
    aged,event3=settle_chase_quote_v1(
        stale,arm=ARMS[0],quote=quote(9,30103),
        now=START+timedelta(seconds=20))
    assert aged["trades"]==0
    assert aged["stale_quotes"]==1
    assert event3["action"]=="STALE_QUOTE_NO_TRADE"


def test_restart_bootstrap_does_not_backfill_profits_or_orders(tmp_path):
    db=str(tmp_path/"chase.db")
    rec=HyperQuoteRecorder(db)
    for sec in range(20):
        px=30000+4*sec
        assert rec.observe(SimpleNamespace(
            market="US Tech 100 NAS",uic=4912,asset_type="CfdOnIndex",
            bid=px-1,ask=px+1,observed_at=stamp(sec)
        ),tradable=True,now=START+timedelta(seconds=sec))
    assert process_chase_cycle_v1(db_path=db,
        now=START+timedelta(seconds=20))==0
    tracks,points=chase_snapshot_v1(db_path=db)
    assert len(tracks)==2 and points==[]
    assert all(t["trades"]==0 and t["ticks"]==0 for t in tracks)
    for sec in range(20,35):
        px=30000+4*sec
        rec.observe(SimpleNamespace(
            market="US Tech 100 NAS",uic=4912,asset_type="CfdOnIndex",
            bid=px-1,ask=px+1,observed_at=stamp(sec)
        ),tradable=True,now=START+timedelta(seconds=sec))
        process_chase_cycle_v1(db_path=db,now=START+timedelta(seconds=sec))
    tracks,points=chase_snapshot_v1(db_path=db)
    assert len(tracks)==2
    assert all(t["ticks"]==15 for t in tracks)
    assert any(t["trades"]>=1 for t in tracks)
    count=len(points)
    process_chase_cycle_v1(db_path=db,now=START+timedelta(seconds=34))
    assert len(chase_snapshot_v1(db_path=db)[1])==count
    with connect(db) as conn:
        # Only owned PAPER tables, no broker/live/order tables.
        tables={r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert "lsim_hyper_chase_tracks" in tables
        assert "autotrader_v3_execution_events" not in tables


def test_lab_integration_paper_only_while_live_unchanged():
    worker=Path("live_sim_lab_worker_v1.py").read_text()
    ui=Path("pages/0_Strategy_Lab_V2.py").read_text()
    src=Path("live_sim_hyper_chase_10s_v1.py").read_text()
    assert "process_chase_cycle_v1(db_path=db_path)" in worker
    assert "HyperChase · 10s PAPER" in ui
    assert "render_hyper_chase_v1()" in ui
    assert "DIRECT_FLIP" in src
    for forbidden in (
        "place_order(","_post(","trade/v2/orders",
        "run_v3_live_cycle_v1(","set_live_enabled_v3(",
    ):
        assert forbidden not in src
        assert forbidden not in Path("strategy_lab_v2_hyper_chase_ui.py").read_text()
