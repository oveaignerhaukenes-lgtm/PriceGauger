from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
import pytest
from database import connect
from autotrader_impulse_catcher_v14 import config_v14,ImpulseCatcherV14,preview,load_settings,save_settings,KEYS
from autotrader_impulse_catcher_replay_v1 import ImpulseQuote
from autotrader_v3_tick_shadow_live_v1 import _new_model,_encode_model,_decode_model,TICK_RUNTIME_KEYS
from autotrader_v3_registry_v1 import strategy_v3,live_config_issues_v3
from autotrader_v3_strategy_registry_v1 import strategy_adapter_v3

T=datetime(2026,11,25,12,tzinfo=timezone.utc)

def quote(m,i,p):
    return m.on_quote(T+timedelta(seconds=i),p-.5,p+.5)

@pytest.mark.parametrize("side",["LONG","SHORT"])
def test_live_registry_and_persisted_state(side):
    key=f"impulse-catcher-{side.lower()}-v1-4"
    spec=strategy_v3(key)
    assert spec.runtime_key in TICK_RUNTIME_KEYS
    assert strategy_adapter_v3(spec.runtime_key).live_route_enabled
    assert not live_config_issues_v3(strategy_key=key,timeframe="1m",control_mode="Manuell",modifiers=())
    m=_new_model(key,{"minimum_hold_seconds":30})
    m.entered_at=T;m.target=side;m.entry_mid=100.;m.extreme=100.;m.samples.append((T,100.))
    d=_decode_model(key,_encode_model(key,m),{"minimum_hold_seconds":30})
    assert d.entered_at==T and d.target==side and d.config.minimum_hold_seconds==30

@pytest.mark.parametrize("side",["LONG","SHORT"])
def test_hold_blocks_normal_but_not_urgent_or_gap(side):
    sign=1 if side=="LONG" else -1
    def held():
        m=ImpulseCatcherV14(config=config_v14(side,{"minimum_hold_seconds":30,"exhaustion_seconds":0,"exit_confirmation_seconds":0,"minimum_retrace_points":3.,"retrace_fraction":.05}))
        m.target=side;m.entered_at=m.last_extreme_at=T;m.entry_mid=100.;m.extreme=100.+sign*20
        return m
    m=held()
    assert quote(m,1,100+sign*15) is None
    assert quote(m,2,100+sign*5).reason=="URGENT_REVERSAL"
    m=held();quote(m,0,100+sign*20)
    assert quote(m,9,100+sign*20).reason=="QUOTE_GAP_FLAT"

def test_entry_confirmation_and_preview_causality():
    c=config_v14("LONG",{"entry_confirmation_seconds":3,"minimum_directional_efficiency":.5,"fast_window":3,"slow_window":10})
    q=[ImpulseQuote(T+timedelta(seconds=i),p-.5,p+.5) for i,p in enumerate([100.+(i%2)*.2 for i in range(80)]+[100.+5*i for i in range(1,12)])]
    rows=preview(q,c)
    entries=[i for i,r in enumerate(rows) if r["decision"]=="QUALIFIED_IMPULSE_V14"]
    assert entries
    j=entries[0]
    assert j>=3 and all(rows[k]["gate"]=="ENTRY_CONFIRM" for k in range(j-3,j))
    assert preview(q[:j+1],c)==rows[:j+1]
    assert preview(q,config_v14("LONG",{"entry_confirmation_seconds":0,"fast_window":3,"slow_window":10}))

def test_independent_settings_and_invalid_bounds(tmp_path):
    path=str(tmp_path/"a.db")
    key="impulse-catcher-long-v1-4"
    with connect(path) as db:
        save_settings(db,"a",key,{"minimum_hold_seconds":30,"entry_indicators":["rsi"]})
        assert load_settings(db,"a",key)["minimum_hold_seconds"]==30
        assert load_settings(db,"b",key)["minimum_hold_seconds"]==15
        assert load_settings(db,"a","impulse-catcher-short-v1-4")["entry_indicators"]==[]
    with pytest.raises(ValueError):config_v14("LONG",{"fast_window":15,"slow_window":6})
    with pytest.raises(ValueError):config_v14("LONG",{"entry_indicators":["fake"]})
    with pytest.raises(ValueError):config_v14("LONG",{"macd_fast":30,"macd_slow":8})


def test_close_latch_preserves_flat_until_broker_reconciliation():
    c=config_v14("LONG",{"entry_confirmation_seconds":0,"fast_window":3,"slow_window":10})
    quotes=[100.+(i%2)*.2 for i in range(80)]+[100.+5*i for i in range(1,12)]
    m=ImpulseCatcherV14(config=c)
    for i,p in enumerate(quotes):
        assert m.on_quote(T+timedelta(seconds=i),p-.5,p+.5,allow_entry=False) is None
    assert m.target=="FLAT" and m.trace["gate"]=="WAIT_BROKER_FLAT"
    assert m.candidate_at is None

def test_missing_ticks_do_not_count_as_exit_confirmation():
    c=config_v14("LONG",{"minimum_hold_seconds":0,"exhaustion_seconds":0,
                         "minimum_retrace_points":3.,"retrace_fraction":.05,"exit_confirmation_seconds":3})
    m=ImpulseCatcherV14(config=c)
    m.target="LONG";m.entry_mid=100.;m.extreme=120.;m.entered_at=m.last_extreme_at=T
    assert quote(m,1,115.) is None
    assert quote(m,5,115.) is None
    assert m.retrace_at==T+timedelta(seconds=5)
    assert quote(m,6,115.) is None
    assert quote(m,7,115.) is None
    assert quote(m,8,115.).reason=="CONFIRMED_EXIT"


def test_overlay_uses_real_timestamp_series_and_visible_gap():
    from autotrader_ic14_ui import make_preview_figure
    c=config_v14("LONG")
    quotes=[ImpulseQuote(T,99.,101.),ImpulseQuote(T+timedelta(seconds=12),100.,102.)]
    fig=make_preview_figure(preview(quotes,c))
    assert len(fig.data[0].x)==3
    assert datetime.fromisoformat(fig.data[0].x[0])==T
    assert datetime.fromisoformat(fig.data[0].x[-1])==quotes[-1].at
    assert len(fig.data)>=8
