"""Per-instance price/indicator audit and immutable AI evidence memory."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from database import connect

from autotrader_v3_ai_decision_memory_v1 import (
    load_ai_decisions_v1,record_ai_decision_v1,
)
from autotrader_v3_instance_inspection_v1 import (
    build_instance_inspection_figure_v1,load_instance_executions_v1,
    resample_complete_candles_v1,
)

BASE=datetime(2026,10,19,19,0,tzinfo=timezone.utc)


def minute(i):
    return SimpleNamespace(
        bar_time=(BASE+timedelta(minutes=i)).isoformat(),
        market_name="US Tech100",open=100+i,high=101+i,
        low=99+i,close=100.5+i,volume=1.0)


def test_resample_drops_forming_and_missing_candles_without_backfill():
    data=[minute(i) for i in range(46) if i != 5]
    # Minute 45 is still forming, so cutoff at minute 45 excludes it.
    out=resample_complete_candles_v1(
        data,timeframe_minutes=2,now=BASE+timedelta(minutes=45,seconds=30))
    times=[x.bar_time for x in out]
    assert (BASE+timedelta(minutes=4)).isoformat() not in times
    assert (BASE+timedelta(minutes=44)).isoformat() in times
    assert (BASE+timedelta(minutes=45)).isoformat() not in times
    first=out[0]
    assert (first.open,first.high,first.low,first.close,first.volume)==(
        100,102,99,101.5,2.)
    assert len(out)==21


def test_chart_contains_price_macd_stoch_and_exact_execution_marker():
    data=[minute(i) for i in range(100)]
    bars=resample_complete_candles_v1(
        data,timeframe_minutes=1,now=BASE+timedelta(minutes=101))
    assert len(bars)==100
    fig=build_instance_inspection_figure_v1(
        bars,timeframe_minutes=1,executions=[{
            "executed_at":BASE+timedelta(minutes=75,seconds=30),
            "action":"OPEN","side":"Buy","amount":0.01,
            "inventory_after":0.01,
        }],ai_decisions=[{
            "evaluated_at":BASE+timedelta(minutes=80),
            "mode":"SHADOW","action":"FLAT",
            "reason":"momentum contracting",
        }])
    assert any(x.type=="candlestick" for x in fig.data)
    assert any(x.name=="MACD" for x in fig.data)
    assert any(x.name=="Signal" for x in fig.data)
    assert any(x.name=="Histogram" for x in fig.data)
    assert any(x.name=="%K" for x in fig.data)
    assert any(x.name=="%D" for x in fig.data)
    assert any(x.marker.symbol=="diamond" for x in fig.data
               if x.type=="scatter" and x.marker.symbol)
    assert any(x.marker.symbol=="triangle-up" for x in fig.data
               if x.type=="scatter" and x.marker.symbol)
    # No marker changes the price or technical indicator samples.
    fig_base=build_instance_inspection_figure_v1(
        bars,timeframe_minutes=1)
    assert tuple(fig_base.data[0].close)==tuple(fig.data[0].close)
    assert tuple(next(x.y for x in fig_base.data if x.name=="MACD"))==tuple(
        next(x.y for x in fig.data if x.name=="MACD"))


def test_trade_audit_filters_exact_instance_and_account(tmp_path):
    path=str(tmp_path/"events.db")
    with connect(path) as db:
        db.execute("""CREATE TABLE autotrader_v3_execution_events (
            executed_at TIMESTAMPTZ, action TEXT, side TEXT, amount REAL,
            inventory_before REAL, inventory_after REAL, request_key TEXT,
            instance_id TEXT,account_id TEXT
        )""")
        for inst,account,req in (
            ("chosen","account-1","one"),
            ("other","account-1","two"),
            ("chosen","account-2","three"),
        ):
            db.execute("""INSERT INTO autotrader_v3_execution_events
                VALUES (?,?,?,?,?,?,?,?,?)""",(
                BASE.isoformat(),"OPEN","Buy",.01,0.,.01,req,inst,account))
    events=load_instance_executions_v1(
        instance_id="chosen",account_id="account-1",
        after=BASE-timedelta(minutes=1),db_path=path)
    assert [x["request_key"] for x in events]==["one"]
    assert all(x["account_id"] not in x for x in events)


def test_ai_memory_is_immutable_causal_and_account_scoped(tmp_path):
    path=str(tmp_path/"ai.db")
    kwargs=dict(
        decision_id="decision-1",instance_id="tech100-C",
        account_id="account-1",instrument_id=99,
        strategy_key="macd-flip",evaluated_at=BASE+timedelta(minutes=1),
        evidence_as_of=BASE,model_id="experimental-ai-v1",
        mode="SHADOW",action="FLAT",confidence=.72,
        reason="Momentum contracted while price broke local support",
        evidence={"macd":{"hist":.04},"price":{"return_30s":-.003},
                  "saxo_open_pnl":-8.5},
        db_path=path,
    )
    assert record_ai_decision_v1(**kwargs)
    assert record_ai_decision_v1(**kwargs) is False
    rows=load_ai_decisions_v1(instance_id="tech100-C",account_id="account-1",
                             instrument_id=99,db_path=path)
    assert len(rows)==1
    assert rows[0]["action"]=="FLAT" and rows[0]["mode"]=="SHADOW"
    assert len(rows[0]["evidence_hash"])==64
    assert not load_ai_decisions_v1(
        instance_id="tech100-C",account_id="account-2",
        instrument_id=99,db_path=path)
    assert not load_ai_decisions_v1(
        instance_id="tech100-C",account_id="account-1",
        instrument_id=100,db_path=path)
    with pytest.raises(ValueError,match="immutable"):
        record_ai_decision_v1(**{**kwargs,"action":"REVERSE"})
    with pytest.raises(ValueError,match="future evidence"):
        record_ai_decision_v1(**{
            **kwargs,"decision_id":"future",
            "evidence_as_of":BASE+timedelta(minutes=2)})
    with pytest.raises(ValueError,match="unsupported"):
        record_ai_decision_v1(**{**kwargs,"decision_id":"bad",
                                 "action":"MARKET_BUY"})


def test_control_surfaces_share_lazy_per_instance_panel_without_saxo_mutation():
    fleet=Path("autotrader_v3_fleet_ui_v1.py").read_text()
    desk=Path("tradingdesk_automanage_panel_v2.py").read_text()
    panel=Path("autotrader_v3_instance_inspection_v1.py").read_text()
    assert "render_v3_instance_inspection_v1(item,key_prefix='fleet')" in fleet
    assert 'render_v3_instance_inspection_v1(by_id[selected],key_prefix="tradingdesk")' in desk
    assert 'st.toggle("Vis handelskart, MACD, Stochastic og AI-minne"' in panel
    assert 'if not st.toggle(' in panel and 'return' in panel
    for forbidden in ("place_order(", "set_live_enabled_v3(", "_post(",
                      "send_order(", "cancel_order("):
        assert forbidden not in panel
    assert "IKKE bekreftet Saxo-fillpris" in panel
