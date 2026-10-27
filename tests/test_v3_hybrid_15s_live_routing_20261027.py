"""V2.3 hybrid LIVE routing is gated by closed 15s BBO, not micro-repeat."""
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace

import pytest

import autotrader_v3_live_runtime_v1 as runtime
import autotrader_v3_macd_stoch_v23_hybrid as hybrid
from database import connect

NOW=datetime(2026,10,27,18,4,0,tzinfo=timezone.utc)


def test_hybrid_quote_wake_is_exact_strategy_and_live_armed_selection(monkeypatch):
    inst=SimpleNamespace(pilot_key="v3",strategy_key=hybrid.RUNTIME_KEY)
    assert runtime._fast_quote_eligible_v3(inst,db_path="nonexistent.db")
    code=__import__("inspect").getsource(runtime.run_v3_live_cycle_v1)
    assert "elif e.strategy_key == HYBRID_KEY" in code
    assert "decision=evaluate_hybrid_live_v3(" in code
    assert "HYBRID_KEY}):" in code
    assert "reserve_order_v3(" in code
    assert "broker.precheck(order)" in code
    assert "reconcile_position_v3(" in code


def test_hybrid_closed_15s_decision_once_then_no_duplicate_build(monkeypatch,tmp_path):
    path=str(tmp_path/"v3_hybrid.db")
    with connect(path) as db:
        db.execute("""CREATE TABLE lsim_hyper_quotes_1s(
            provider_uic INTEGER,quote_at TEXT,received_at TEXT,
            bid REAL,ask REAL)""")
        for sec in range(240):
            at=NOW-timedelta(seconds=240-sec)
            price=20000+sec*.5
            db.execute("""INSERT INTO lsim_hyper_quotes_1s
             (provider_uic,quote_at,received_at,bid,ask) VALUES(?,?,?,?,?)""",
             (4912,at.isoformat(),
              (at+timedelta(milliseconds=100)).isoformat(),
              price-1,price+1))
    marker=SimpleNamespace(bar_time=(NOW-timedelta(minutes=1)).isoformat(),
                            close=20000,open=20000,high=20001,low=19999)
    class FakeStore:
        def __init__(self,_):pass
        def load_instrument_range(self,**k):
            return tuple(SimpleNamespace(point=marker) for _ in range(60))
    monkeypatch.setattr(hybrid,"CanonicalMarketBarStoreV2",FakeStore)
    monkeypatch.setattr(hybrid,"closed_bars_v2",lambda *a,**k:(marker,)*60)
    monkeypatch.setattr(hybrid,"macd_observations_v2",
                        lambda *a,**k:(SimpleNamespace(spread=.4),)*2)
    monkeypatch.setattr(hybrid,"macro_direction_from_closed_1m",
                        lambda *a,**k:(1,"MACRO_ALIGNED_TEST"))
    args=dict(trader_id="v3",strategy_key=hybrid.RUNTIME_KEY,
        account_uic=4912,instrument_id=17,market_name="US Tech 100 NAS",
        actual_amount=0.,tranche=.01,max_inventory=.05,db_path=path,now=NOW)
    first=hybrid.evaluate_hybrid_live_v3(**args)
    assert first.decision.target.amount==pytest.approx(.01)
    assert first.decision.action=="MICRO_ENTRY_2X15S"
    assert first.is_new
    second=hybrid.evaluate_hybrid_live_v3(**args)
    assert second.decision.target.amount==0.
    assert "DUPLICATE" in second.decision.action
    assert not second.is_new


def test_hybrid_quote_wake_requires_native_1m_selection():
    from autotrader_v3_registry_v1 import live_config_issues_v3
    assert live_config_issues_v3(
        strategy_key=hybrid.CATALOG_KEY,timeframe="2m",
        control_mode="Manuell",modifiers=())
