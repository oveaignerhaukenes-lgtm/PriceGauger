"""Durable causally aligned V3 market-state research (no Saxo calls/orders).

At each available closed 1m bar, snapshot exact instrument/state/strategy.
Only *later* append the next five completed 1m closes as a PRICE proxy.
Neither price movement nor unadjusted account NAV equals strategy net P/L.
The observer never calls the live STOP/GO writer or chooses a block action.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd

from autotrader_engine_account_ownership_v1 import ENGINE_V3,load_account_owner_v1
from autotrader_v3_config_v1 import load_autotrader_config_v3
from autotrader_v3_instance_registry_v1 import load_v3_instances_v1
from autotrader_v3_live_authority_v1 import live_authority_armed_v3
from canonical_market_bars_v2 import CanonicalMarketBarStoreV2
from database import connect,run_postgres_schema_once_v1
from market_models_state_v1 import quantize_market_state_v1


def _utc(value):
    dt=value if isinstance(value,datetime) else datetime.fromisoformat(str(value).replace('Z','+00:00'))
    if dt.tzinfo is None:
        raise ValueError('timezone-aware observation required')
    return dt.astimezone(timezone.utc)


def ensure_market_state_observer_schema_v1(db_path='pricegauger.db'):
    def initialize():
        with connect(db_path) as db:
            db.execute('''CREATE TABLE IF NOT EXISTS pg_v3_state_strategy_observations_v1(
                instance_id TEXT NOT NULL,account_id TEXT NOT NULL,
                instrument_id INTEGER NOT NULL,uic INTEGER NOT NULL,
                strategy_key TEXT NOT NULL,timeframe TEXT NOT NULL,
                observed_as_of TEXT NOT NULL,state_key TEXT NOT NULL,
                efficiency DOUBLE PRECISION NOT NULL,
                direction_changes INTEGER NOT NULL,
                volatility_pct_1m DOUBLE PRECISION NOT NULL,
                rhythm_evidence TEXT NOT NULL,
                close_price DOUBLE PRECISION NOT NULL,
                future_5m_price_return_pct DOUBLE PRECISION,
                future_5m_completed_at TEXT,
                PRIMARY KEY(instance_id,observed_as_of))''')
            db.execute('''CREATE INDEX IF NOT EXISTS ix_v3_state_strategy_pending_v1
                ON pg_v3_state_strategy_observations_v1(
                instrument_id,future_5m_completed_at,observed_as_of)''')
    run_postgres_schema_once_v1('v3_state_strategy_observations_v1',initialize)


def _contiguous_completed_bars(store,instrument_id:int,*,end:datetime,
                               count:int):
    bars=store.load_instrument_range(
        instrument_id=instrument_id,
        start=end-timedelta(minutes=count+3),end=end,
        limit=count+5,
    )
    # First bar's open time is UTC end-(count-1)m; last bar *must* have closed.
    selected=tuple(b for b in bars if _utc(b.bar_time)<=end)[-count:]
    if len(selected)!=count:
        return ()
    if any(_utc(b.bar_time)!=end-timedelta(minutes=count-1-i)
           for i,b in enumerate(selected)):
        return ()
    return selected


def observe_market_strategy_once_v1(*,db_path='pricegauger.db',now=None):
    """5m sidecar; missing candles/accounts are UNKNOWN, never interpolated."""
    clock=_utc(now or datetime.now(timezone.utc))
    last_closed_open=clock.replace(second=0,microsecond=0)-timedelta(minutes=1)
    ensure_market_state_observer_schema_v1(db_path)
    store=CanonicalMarketBarStoreV2(db_path)
    saved=completed=skipped=errors=0
    for inst in load_v3_instances_v1(db_path=db_path):
        try:
            if not live_authority_armed_v3(inst.instance_id,db_path=db_path):
                continue
            owner=load_account_owner_v1(inst.account_id,db_path=db_path)
            if owner is None or owner.engine_id!=ENGINE_V3 or owner.owner_key!=inst.instance_id:
                continue
            cfg=load_autotrader_config_v3(inst.instance_id,db_path=db_path)
            bars=_contiguous_completed_bars(store,int(inst.instrument_id),
                                           end=last_closed_open,count=61)
            if not bars:
                skipped+=1
                continue
            times=pd.to_datetime([_utc(x.bar_time) for x in bars],utc=True)
            state=quantize_market_state_v1(pd.Series(
                [float(x.close) for x in bars],index=times,dtype=float))
            if state is None or _utc(state.as_of)!=last_closed_open+timedelta(minutes=1):
                skipped+=1
                continue
            with connect(db_path) as db:
                cursor=db.execute('''INSERT INTO pg_v3_state_strategy_observations_v1(
                    instance_id,account_id,instrument_id,uic,strategy_key,timeframe,
                    observed_as_of,state_key,efficiency,direction_changes,
                    volatility_pct_1m,rhythm_evidence,close_price)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(instance_id,observed_as_of) DO NOTHING''',(
                    inst.instance_id,inst.account_id,int(inst.instrument_id),int(inst.uic),
                    cfg.strategy_key,cfg.timeframe,_utc(state.as_of).isoformat(),
                    state.state_key,state.efficiency,state.direction_changes,
                    state.volatility_pct_1m,state.rhythm_evidence,float(bars[-1].close)))
                saved+=int(cursor.rowcount==1)
        except Exception:
            # Research failure must never impede Saxo worker or another account.
            errors+=1
    # Fill only matured observations, strictly after the 5m future has closed.
    with connect(db_path) as db:
        pending=db.execute('''SELECT instance_id,instrument_id,observed_as_of,close_price
            FROM pg_v3_state_strategy_observations_v1
            WHERE future_5m_completed_at IS NULL
              AND observed_as_of>=? AND observed_as_of<=?
            ORDER BY observed_as_of DESC LIMIT 120''',
            ((clock-timedelta(days=1)).isoformat(),
             (clock-timedelta(minutes=5)).isoformat())).fetchall()
    for row in pending:
        try:
            as_of=_utc(row['observed_as_of'])
            final_open=as_of+timedelta(minutes=4)
            future=_contiguous_completed_bars(store,int(row['instrument_id']),
                                              end=final_open,count=5)
            if not future or final_open+timedelta(minutes=1)>clock:
                skipped+=1
                continue
            change=100*(float(future[-1].close)/float(row['close_price'])-1)
            with connect(db_path) as db:
                result=db.execute('''UPDATE pg_v3_state_strategy_observations_v1
                    SET future_5m_price_return_pct=?,future_5m_completed_at=?
                    WHERE instance_id=? AND observed_as_of=?
                    AND future_5m_completed_at IS NULL''',(
                    change,(final_open+timedelta(minutes=1)).isoformat(),
                    row['instance_id'],row['observed_as_of']))
                completed+=int(result.rowcount==1)
        except Exception:
            errors+=1
    return {'snapshots':saved,'matured':completed,'skipped':skipped,'errors':errors}


__all__=['ensure_market_state_observer_schema_v1','observe_market_strategy_once_v1']
