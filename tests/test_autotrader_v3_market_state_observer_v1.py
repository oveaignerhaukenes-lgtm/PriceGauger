"""Closed-bar market observations: no future leakage or broker impact."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime,timedelta,timezone
from pathlib import Path
from types import SimpleNamespace

import autotrader_v3_market_state_observer_v1 as observer


START=datetime(2026,11,19,8,59,tzinfo=timezone.utc)


@dataclass(frozen=True)
class FakeBar:
    bar_time:str
    close:float


class FakeStore:
    def __init__(self,rows):
        self.rows=rows

    def load_instrument_range(self,*,instrument_id,start,end,limit):
        return tuple(r for r in self.rows if start<=datetime.fromisoformat(r.bar_time)<=end)[:limit]


def make_bars(n):
    # Nontrivial alternating direction and a slight drift; no flat prices.
    price=100.
    result=[]
    for i in range(n):
        price+=(.23 if i%2 else -.11)
        result.append(FakeBar((START+timedelta(minutes=i)).isoformat(),price))
    return result


def configure(monkeypatch,store):
    inst=SimpleNamespace(instance_id='exact-v3',account_id='account-x',
        instrument_id=37,uic=4912)
    monkeypatch.setattr(observer,'load_v3_instances_v1',lambda **k:(inst,))
    monkeypatch.setattr(observer,'live_authority_armed_v3',lambda *a,**k:True)
    monkeypatch.setattr(observer,'load_account_owner_v1',lambda *a,**k:
                        SimpleNamespace(engine_id=observer.ENGINE_V3,owner_key='exact-v3'))
    monkeypatch.setattr(observer,'load_autotrader_config_v3',lambda *a,**k:
                        SimpleNamespace(strategy_key='impulse-long',timeframe='1m'))
    monkeypatch.setattr(observer,'CanonicalMarketBarStoreV2',lambda path:store)


def test_observation_then_later_matured_price_label_without_lookahead(tmp_path,monkeypatch):
    path=str(tmp_path/'observer.db')
    bars=make_bars(66)
    configure(monkeypatch,FakeStore(bars[:61]))
    t=START+timedelta(minutes=61)
    first=observer.observe_market_strategy_once_v1(db_path=path,now=t)
    assert first['snapshots']==1 and first['matured']==0 and first['errors']==0
    with sqlite3.connect(path) as db:
        row=db.execute('SELECT strategy_key,state_key,observed_as_of,close_price,future_5m_price_return_pct FROM pg_v3_state_strategy_observations_v1').fetchone()
        assert row[0]=='impulse-long' and '/' in row[1]
        assert row[2]==t.isoformat()
        assert row[4] is None
    configure(monkeypatch,FakeStore(bars))
    second=observer.observe_market_strategy_once_v1(db_path=path,now=t+timedelta(minutes=5))
    assert second['matured']==1 and second['errors']==0
    with sqlite3.connect(path) as db:
        value=db.execute('''SELECT future_5m_price_return_pct FROM
            pg_v3_state_strategy_observations_v1 WHERE observed_as_of=?''',(t.isoformat(),)).fetchone()[0]
    expected=100*(bars[65].close/bars[60].close-1)
    assert abs(value-expected)<1e-10
    duplicate=observer.observe_market_strategy_once_v1(db_path=path,now=t+timedelta(minutes=5))
    assert duplicate['snapshots']==0 and duplicate['matured']==0


def test_gaps_refuse_both_state_and_future_labels(tmp_path,monkeypatch):
    path=str(tmp_path/'gaps.db')
    bars=make_bars(66)
    configure(monkeypatch,FakeStore(bars[:29]+bars[30:61]))
    clock=START+timedelta(minutes=61)
    assert observer.observe_market_strategy_once_v1(db_path=path,now=clock)['snapshots']==0
    configure(monkeypatch,FakeStore(bars[:61]))
    observer.observe_market_strategy_once_v1(db_path=path,now=clock)
    configure(monkeypatch,FakeStore(bars[:63]+bars[64:]))
    assert observer.observe_market_strategy_once_v1(db_path=path,now=clock+timedelta(minutes=5))['matured']==0


def test_wrong_owner_and_unarmed_never_sample(tmp_path,monkeypatch):
    path=str(tmp_path/'scoped.db')
    configure(monkeypatch,FakeStore(make_bars(61)))
    monkeypatch.setattr(observer,'load_account_owner_v1',lambda *a,**k:
                        SimpleNamespace(engine_id=observer.ENGINE_V3,owner_key='other'))
    clock=START+timedelta(minutes=61)
    assert observer.observe_market_strategy_once_v1(db_path=path,now=clock)['snapshots']==0
    monkeypatch.setattr(observer,'live_authority_armed_v3',lambda *a,**k:False)
    assert observer.observe_market_strategy_once_v1(db_path=path,now=clock)['snapshots']==0


def test_observer_is_independent_of_order_and_filter_writers():
    source=Path('autotrader_v3_market_state_observer_v1.py').read_text(encoding='utf8')
    assert 'set_trade_filter_v1' not in source
    assert 'place_order(' not in source
    assert 'broker.' not in source
    worker=Path('telegram_multi_worker.py').read_text(encoding='utf8')
    assert 'observe_market_strategy_once_v1(db_path=str(db_path))' in worker
