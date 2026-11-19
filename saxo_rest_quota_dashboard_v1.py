"""Read-only UI data contract and off-hot-path persistence for Saxo LIVE usage.

These are measurements made by PriceGauger processes, not the complete Saxo
application account. A quota percentage is displayed only when Saxo returned
both Limit and Remaining in the response headers for that dimension.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime,timedelta,timezone
import json
from uuid import uuid4

from database import connect,run_postgres_schema_once_v1
from saxo_rest_telemetry_v1 import drain_saxo_rest_usage_v1,restore_saxo_rest_usage_v1


_PRODUCER_ID=uuid4().hex


def ensure_saxo_rest_usage_schema_v1(db_path='pricegauger.db'):
    def initialize():
        with connect(db_path) as db:
            db.execute('''CREATE TABLE IF NOT EXISTS pg_saxo_rest_usage_windows_v1(
                producer_id TEXT NOT NULL,window_ended_at TEXT NOT NULL,
                method TEXT NOT NULL,endpoint TEXT NOT NULL,
                call_count INTEGER NOT NULL,http429_count INTEGER NOT NULL,
                quota_json TEXT NOT NULL,
                PRIMARY KEY(producer_id,window_ended_at,method,endpoint))''')
            db.execute('''CREATE INDEX IF NOT EXISTS ix_saxo_usage_window_v1
                ON pg_saxo_rest_usage_windows_v1(window_ended_at DESC)''')
    run_postgres_schema_once_v1('saxo_rest_usage_windows_v1',initialize)


def flush_saxo_rest_usage_v1(*,db_path='pricegauger.db') -> int:
    """Called by the existing telemetry sidecar, NEVER from a Saxo request."""
    pending=drain_saxo_rest_usage_v1()
    if not pending:
        return 0
    try:
        ensure_saxo_rest_usage_schema_v1(db_path)
        with connect(db_path) as db:
            for row in pending:
                db.execute('''INSERT INTO pg_saxo_rest_usage_windows_v1(
                    producer_id,window_ended_at,method,endpoint,call_count,
                    http429_count,quota_json) VALUES(?,?,?,?,?,?,?)
                    ON CONFLICT(producer_id,window_ended_at,method,endpoint)
                    DO NOTHING''',(
                    _PRODUCER_ID,row['window_ended_at'],row['method'],row['endpoint'],
                    int(row['call_count']),int(row['http429_count']),
                    json.dumps(row.get('quota') or {},sort_keys=True),
                ))
            db.execute('''DELETE FROM pg_saxo_rest_usage_windows_v1
                WHERE window_ended_at<?''',(
                (datetime.now(timezone.utc)-timedelta(days=7)).isoformat(),))
    except Exception:
        restore_saxo_rest_usage_v1(pending)
        raise
    return len(pending)


def load_saxo_rest_usage_v1(*,minutes:int=60,db_path='pricegauger.db',
                            now:datetime|None=None) -> tuple[dict,...]:
    span=max(5,min(7*24*60,int(minutes)))
    clock=(now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    try:
        with connect(db_path) as db:
            rows=db.execute('''SELECT window_ended_at,method,endpoint,
                call_count,http429_count,quota_json
                FROM pg_saxo_rest_usage_windows_v1
                WHERE window_ended_at>=?
                ORDER BY window_ended_at DESC LIMIT 100000''',
                ((clock-timedelta(minutes=span)).isoformat(),)).fetchall()
    except Exception as exc:
        # A newly deployed read-only web service can precede its worker's
        # first schema creation. Unexpected DB failures must remain visible.
        if 'no such table' in str(exc).lower() or (
            'does not exist' in str(exc).lower() and
            'pg_saxo_rest_usage_windows_v1' in str(exc).lower()
        ):
            return ()
        raise
    result=[]
    for row in rows:
        data=dict(row)
        try:
            data['quota']=json.loads(data.pop('quota_json'))
        except (ValueError,TypeError):
            data['quota']={}
        result.append(data)
    return tuple(result)


def summarize_saxo_rest_usage_v1(rows) -> dict:
    by_endpoint=defaultdict(lambda:{'calls':0,'http429':0})
    by_minute=defaultdict(lambda:{'calls':0,'http429':0})
    quotas={}
    total=blocked=0
    for row in rows:
        calls=int(row['call_count']); failures=int(row['http429_count'])
        total+=calls; blocked+=failures
        key=(str(row['method']),str(row['endpoint']))
        by_endpoint[key]['calls']+=calls
        by_endpoint[key]['http429']+=failures
        minute=str(row['window_ended_at'])[:16]
        by_minute[minute]['calls']+=calls
        by_minute[minute]['http429']+=failures
        for dimension,fields in (row.get('quota') or {}).items():
            if not isinstance(fields,dict):
                continue
            try:
                limit=int(fields['limit']); remaining=int(fields['remaining'])
                reset=(int(fields['reset']) if 'reset' in fields else None)
                if limit<=0 or not 0<=remaining<=limit or (reset is not None and reset<0):
                    continue
            except (TypeError,ValueError,KeyError):
                continue
            candidate={
                'dimension':str(dimension),'source':f'{key[0]} {key[1]}',
                'limit':limit,'remaining':remaining,
                'used_pct':round(100*(limit-remaining)/limit,3),
                'reset_seconds':reset,'sampled_at':str(row['window_ended_at']),
            }
            previous=quotas.get(dimension)
            if previous is None or candidate['sampled_at']>previous['sampled_at']:
                quotas[dimension]=candidate
    return {
        'calls':total,'http429':blocked,
        'endpoints':tuple({'method':method,'endpoint':path,**count}
                          for (method,path),count in sorted(by_endpoint.items(),
                                                             key=lambda kv:-kv[1]['calls'])),
        'minutes':tuple({'minute':minute,**counts}
                        for minute,counts in sorted(by_minute.items())),
        'quotas':tuple(quotas[k] for k in sorted(quotas)),
    }


__all__=['ensure_saxo_rest_usage_schema_v1','flush_saxo_rest_usage_v1',
         'load_saxo_rest_usage_v1','summarize_saxo_rest_usage_v1']
