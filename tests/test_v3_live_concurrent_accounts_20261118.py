"""Concurrency is across Saxo accounts; freshness and ordering stay local."""
from concurrent.futures import Future
from datetime import datetime, timedelta, timezone
import sqlite3
from types import SimpleNamespace

import autotrader_v3_live_runtime_v1 as live
import autotrader_v3_live_bar_watcher_v1 as watcher
import autotrader_v3_hyper_chase_live_v1 as hyper
import autotrader_v3_whipsaw_optin_b_20261013 as optin
import hyper_chase_quote_quality_probe_v1 as quote_quality
import worker


class DelayedPool:
    """A broker that never finishes, to expose head-of-line blocking."""
    calls=[]
    def __init__(self, **kwargs):
        self.lane=kwargs['thread_name_prefix']
    def __enter__(self):
        return self
    def __exit__(self, *_):
        return False
    def submit(self, fn, **kwargs):
        future=Future()
        self.calls.append((self.lane,kwargs,future))
        return future


class StopAfter:
    def __init__(self, n):
        self.n=n
        self.ticks=0
    def is_set(self):
        return self.ticks>=self.n
    def wait(self, seconds):
        self.ticks+=1


def _no_broker_or_db_side_effects(monkeypatch):
    monkeypatch.setattr(optin,'apply_authorized_whipsaw_b_once',lambda **_:None)
    monkeypatch.setattr(quote_quality,'probe_hyper_quote_quality_v1',lambda **_:())


def test_route_groups_all_strategies_for_same_account(monkeypatch):
    instances=(SimpleNamespace(account_id='A',strategy_key='plain'),
               SimpleNamespace(account_id='A',strategy_key='tick'),
               SimpleNamespace(account_id='B',strategy_key='plain'))
    monkeypatch.setattr(live,'_load_owned_armed_runtime_instances_v3',
                        lambda **_: instances)
    monkeypatch.setattr(live,'_fast_quote_eligible_v3',
                        lambda e,**_:e.strategy_key=='tick')
    assert live.owned_live_account_routes_v3() == {'A':True,'B':False}


def test_slow_account_does_not_block_fast_account_and_no_overlap(monkeypatch):
    """Full refresh starts all accounts; subsequent wakes queue, not duplicate."""
    DelayedPool.calls=[]
    _no_broker_or_db_side_effects(monkeypatch)
    stop=StopAfter(4)
    monkeypatch.setattr(worker,'ThreadPoolExecutor',DelayedPool)
    monkeypatch.setattr(worker,'owned_live_account_routes_v3',
                        lambda **_: {'bar-account':False,'quote-account':True})
    monkeypatch.setattr(worker.time,'monotonic',lambda:float(stop.ticks))
    monkeypatch.setattr(watcher,'closed_instrument_cursors_v3',
                        lambda **_: ((7,str(stop.ticks)),))
    monkeypatch.setattr(hyper,'live_hyper_quote_cursors_v3',
                        lambda **_: ((4912,str(stop.ticks)),))
    worker.run_v3_live_fast_loop_v1(db_path='unused.db',stop_event=stop)
    assert len(DelayedPool.calls)==2  # 4 wakes, but each account still busy
    by_account={args['account_ids'][0]:lane for lane,args,_ in DelayedPool.calls}
    assert by_account=={'quote-account':'v3-quote','bar-account':'v3-bars'}
    assert all(args['hyper_quote_only'] is False for _,args,_ in DelayedPool.calls)


def test_queued_tick_wake_runs_after_same_account_finishes(monkeypatch):
    DelayedPool.calls=[]
    _no_broker_or_db_side_effects(monkeypatch)
    stop=StopAfter(3)
    monkeypatch.setattr(worker,'ThreadPoolExecutor',DelayedPool)
    monkeypatch.setattr(worker,'owned_live_account_routes_v3',
                        lambda **_: {'quote-account':True})
    monkeypatch.setattr(worker.time,'monotonic',lambda:float(stop.ticks))
    monkeypatch.setattr(watcher,'closed_instrument_cursors_v3',lambda **_:())
    monkeypatch.setattr(hyper,'live_hyper_quote_cursors_v3',
                        lambda **_: ((4912,str(stop.ticks)),))
    # Completing the first cycle on the second poll releases the queued wake.
    original=stop.wait
    def release(seconds):
        original(seconds)
        if stop.ticks==2:
            DelayedPool.calls[0][2].set_result(0)
    stop.wait=release
    worker.run_v3_live_fast_loop_v1(db_path='unused.db',stop_event=stop)
    assert len(DelayedPool.calls)==2
    assert DelayedPool.calls[0][1]['hyper_quote_only'] is False
    assert DelayedPool.calls[1][1]['hyper_quote_only'] is True


def test_tick_open_expires_against_actual_signal_time(tmp_path):
    db=str(tmp_path/'tick.db')
    now=datetime(2026,11,18,16,12,0,tzinfo=timezone.utc)
    stamp=(now-timedelta(seconds=1)).isoformat()
    key=f'tick:impulse-catcher-long-tick-v1-1:{stamp}:TICK_LONG'
    with sqlite3.connect(db) as conn:
        conn.execute('CREATE TABLE pg_v3_tick_live_state (trader_id TEXT PRIMARY KEY, last_signal_at TEXT)')
        conn.execute('INSERT INTO pg_v3_tick_live_state VALUES (?,?)',(
            'E',(now-timedelta(seconds=3)).isoformat()))
    valid=dict(strategy_key='impulse-catcher-long-tick-v1-1',decision_key=key,
               trader_id='E',db_path=db,clock=now)
    assert live._fresh_quote_open_authorized_v3(**valid)
    with sqlite3.connect(db) as conn:
        conn.execute('UPDATE pg_v3_tick_live_state SET last_signal_at=?',(
            (now-timedelta(seconds=6)).isoformat(),))
    assert not live._fresh_quote_open_authorized_v3(**valid)
    assert not live._fresh_quote_open_authorized_v3(**{**valid,
        'decision_key':'tick:impulse-catcher-long-tick-v1-1:not-a-date:TICK_LONG'})


def test_hyper_open_expiry_preserves_non_tick_strategies():
    now=datetime(2026,11,18,16,12,0,tzinfo=timezone.utc)
    common=dict(trader_id='E',db_path='unused.db',clock=now)
    old=(now-timedelta(seconds=12)).isoformat()
    assert not live._fresh_quote_open_authorized_v3(strategy_key='hyper-chase-10s-fast-v1',
        decision_key=f'quote10:hyper-chase-10s-fast-v1:{old}:CHASE',**common)
    assert live._fresh_quote_open_authorized_v3(strategy_key='macd-stoch-v21-r-short-flat-v1',
        decision_key='any',**common)
