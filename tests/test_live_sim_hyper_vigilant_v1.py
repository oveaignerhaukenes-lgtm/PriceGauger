"""Prospective 1 Hz Stochastic, MACD, price-guard and whipsaw Lab contracts."""
from datetime import datetime,timedelta,timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from database import connect
from live_sim_hyper_quotes_v1 import HyperQuoteRecorder
from live_sim_hyper_vigilant_v1 import (
    ARMS,_features,_sample_feature,_settle_track,_track,adverse_price_guard,
    hyper_snapshot,policy_target,process_hyper_cycle,signal_from_features,
)
import live_sim_lab_worker_v1


BASE=datetime(2026,10,12,18,0,tzinfo=timezone.utc)


def quote_at(offset):
    return (BASE+timedelta(seconds=offset)).isoformat()


def q(offset,price=30000.0):
    return SimpleNamespace(
        market="US Tech 100 NAS",uic=4912,asset_type="CfdOnIndex",
        bid=price-0.5,ask=price+0.5,observed_at=quote_at(offset),
    )


def record(recorder,offset,price=30000,*,tradable=True):
    return recorder.observe(q(offset,price),tradable=tradable,
                            now=BASE+timedelta(seconds=offset))


def test_real_quote_recorder_accepts_one_per_second_no_interpolation(tmp_path):
    path=str(tmp_path/"hyper.db")
    rec=HyperQuoteRecorder(path)
    assert record(rec,0)
    assert not record(rec,0)
    assert not record(rec,1,tradable=False)
    assert record(rec,2)
    late=q(3)
    assert not rec.observe(late,tradable=True,
                           now=BASE+timedelta(seconds=30))
    future=q(10)
    assert not rec.observe(future,tradable=True,
                           now=BASE+timedelta(seconds=2))
    assert not rec.observe(SimpleNamespace(
        market="US Tech 100 NAS",uic=4912,asset_type="CfdOnIndex",
        bid=30002,ask=30001,observed_at=quote_at(4)),
        tradable=True,now=BASE+timedelta(seconds=4))
    with connect(path) as db:
        rows=db.execute("SELECT quote_at,bid,ask FROM lsim_hyper_quotes_1s ORDER BY quote_at").fetchall()
        assert [row["quote_at"] for row in rows]==[quote_at(0),quote_at(2)]


def test_stochastic_primary_macd_only_when_flat():
    f=_features()
    f.update(k=65.0,d=50.0,k_delta=7.0,macd_hist=-100.0)
    assert signal_from_features(f,use_macd=True)==(1,"STOCH_UP",False)
    f.update(k=35.0,d=50.0,k_delta=-7.0,macd_hist=100.0)
    assert signal_from_features(f,use_macd=True)==(-1,"STOCH_DOWN",False)
    f.update(k=50.0,d=50.1,k_delta=0.0,macd_hist=1.0,
             samples=[[quote_at(i),30000+(i//5)] for i in range(60)])
    assert signal_from_features(f,use_macd=False)[0]==0
    assert signal_from_features(f,use_macd=True)[0]==1


def test_price_rise_overrides_short_even_if_stochastic_bearish():
    f=_features()
    for i in range(30):
        # 0.12 % rebound over ~15 seconds, well beyond 0.06% floor.
        f=_sample_feature(f,at=quote_at(i),mid=30000+i*2.5)
    mid=float(f["samples"][-1][1])
    triggered,threshold=adverse_price_guard(
        f,position=-1.0,entry_mid=30010,mid=mid)
    assert triggered is True
    assert threshold>=0.0006
    target,reason,cooldown=policy_target(
        arm="STOCH_PRICE",signal=-1,actual=-1,whipsaw=False,
        price_adverse=True,now=quote_at(29))
    assert (target,reason,cooldown)==(0,"PRICE_GUARD_FLAT",12)
    no_guard=policy_target(
        arm="STOCH_MACD",signal=-1,actual=-1,whipsaw=False,
        price_adverse=True,now=quote_at(29))
    assert no_guard[0]==-1


def test_no_price_override_for_small_move():
    f=_features()
    for i in range(30):
        f=_sample_feature(f,at=quote_at(i),mid=30000+i*0.03)
    triggered,_=adverse_price_guard(
        f,position=-1,entry_mid=30000,mid=f["samples"][-1][1])
    assert not triggered


def test_whipsaw_detector_needs_13_closed_5second_buckets():
    f=_features()
    for i in range(81):
        # Repeated direction alternation every completed five-second interval.
        level=30000+(8 if (i//5)%2 else 0)
        f=_sample_feature(f,at=quote_at(i),mid=level)
    assert f["whipsaw_raw"] is True
    assert f["whipsaw_active"] is True
    assert f["whipsaw_count"]>=1
    # Incomplete subsequent bucket cannot clear the detector immediately.
    first=f["whipsaw_clear_buckets"]
    f=_sample_feature(f,at=quote_at(81),mid=30000)
    assert f["whipsaw_clear_buckets"]==first


def test_whipsaw_pause_reduce_flat_are_independently_bounded():
    for arm,expected in [
        ("WHIP_PAUSE",1.0),("WHIP_REDUCE",0.5),("WHIP_FLAT",0.0)
    ]:
        target,reason,_=policy_target(
            arm=arm,signal=1,actual=1.0,whipsaw=True,
            price_adverse=False,now=quote_at(70))
        assert target==expected
        assert reason.startswith("WHIPSAW_")
    assert policy_target(
        arm="WHIP_PAUSE",signal=1,actual=0,whipsaw=True,
        price_adverse=False,now=quote_at(70))[0]==0
    assert policy_target(
        arm="STOCH_PRICE",signal=1,actual=0,whipsaw=True,
        price_adverse=False,now=quote_at(70))[0]==1


def test_fast_strategy_fails_to_flat_first_before_opposite_side():
    flat=policy_target(
        arm="STOCH_ONLY",signal=-1,actual=1,whipsaw=False,
        price_adverse=False,now=quote_at(90),
    )
    assert flat==(0.0,"SIGNAL_FLAT_BEFORE_REVERSAL",8)
    assert policy_target(
        arm="STOCH_ONLY",signal=-1,actual=0,whipsaw=False,
        price_adverse=False,now=quote_at(91),
        cooldown_until=quote_at(98),
    )[0]==0


def test_next_quote_bid_ask_fill_deducts_cost_and_idempotence():
    f=_features()
    f.update(k=90,d=20,k_delta=8,macd_hist=1,
             last_quote=quote_at(70))
    state=_track()
    first,traded=_settle_track(
        state,arm="STOCH_ONLY",feature=f,
        quote={"quote_at":quote_at(70),"bid":29999,"ask":30001},
        trade_allowed=True)
    assert not traded and first["exposure"]==0 and first["pending"]==1
    f["last_quote"]=quote_at(71)
    second,traded=_settle_track(
        first,arm="STOCH_ONLY",feature=f,
        quote={"quote_at":quote_at(71),"bid":29999,"ask":30001},
        trade_allowed=True)
    assert traded and second["exposure"]==1
    assert second["equity"]<10000
    assert second["spread_cost_nok"]>0 and second["fees_nok"]>0
    replay,traded=_settle_track(
        second,arm="STOCH_ONLY",feature=f,
        quote={"quote_at":quote_at(71),"bid":29999,"ask":30001},
        trade_allowed=True)
    assert not traded
    assert replay==second


def test_forward_bootstrap_never_mints_historical_pnl(tmp_path):
    path=str(tmp_path/"forward.db")
    recorder=HyperQuoteRecorder(path)
    for i in range(90):
        assert record(recorder,i,30000+4*((i//5)%2))
    assert process_hyper_cycle(db_path=path,now=BASE+timedelta(seconds=90))==0
    feeds,tracks,points=hyper_snapshot(db_path=path)
    assert len(feeds)==1 and len(tracks)==6 and not points
    assert all(item["equity"]==10000 and item["ticks"]==0
               for item in tracks)
    assert record(recorder,91,30010)
    assert process_hyper_cycle(db_path=path,now=BASE+timedelta(seconds=91))==1
    assert process_hyper_cycle(db_path=path,now=BASE+timedelta(seconds=91))==0
    _,tracks,points=hyper_snapshot(db_path=path)
    assert all(item["ticks"]==1 for item in tracks)
    assert all(item["trades"]==0 for item in tracks)
    assert len(points)==0 or all(x["quote_at"]==quote_at(91) for x in points)


def test_no_retrospective_fills_after_feed_gap(tmp_path):
    path=str(tmp_path/"gap.db")
    rec=HyperQuoteRecorder(path)
    for i in range(75):
        record(rec,i,30000+i*1.2)
    assert process_hyper_cycle(db_path=path,now=BASE+timedelta(seconds=75))==0
    record(rec,76,30100)
    process_hyper_cycle(db_path=path,now=BASE+timedelta(seconds=76))
    # Next quote arrives after 15s disconnection, cannot fill stale intent.
    record(rec,91,30200)
    process_hyper_cycle(db_path=path,now=BASE+timedelta(seconds=91))
    _,tracks,_=hyper_snapshot(db_path=path)
    assert all(item["trades"]==0 for item in tracks)
    assert all(item["stale_ticks"]>=1 for item in tracks)


def test_research_only_contract_and_own_ui():
    root=Path(__file__).resolve().parent.parent
    for name in ("live_sim_hyper_quotes_v1.py",
                 "live_sim_hyper_vigilant_v1.py","live_sim_lab_worker_v1.py"):
        text=(root/name).read_text()
        assert "place_order(" not in text
        assert "run_v3_live_cycle_v1" not in text
        assert "import saxo_trading" not in text
    ui=(root/"pages/0_Live_Sim_Lab.py").read_text()
    assert 'st.subheader("Hyper-Vigilant Stochastic' in ui
    assert "hyper_snapshot()" in ui
    assert "WHIP_REDUCE" in ui and "WHIP_FLAT" in ui
    stream=(root/"saxo_streaming.py").read_text()
    assert "recorder.observe(" in stream
    assert "tradable=self._hunter_tradable.get" in stream
    assert "name=\"pricegauger-hyper-paper\"" in (
        root/"live_sim_lab_worker_v1.py").read_text()
