from __future__ import annotations

"""Canonical durable V3 execution events.

The execution/reconciliation boundary writes these events. Presentation code may read
this ledger but must never reconstruct V3 executions from strategy enrollment or order
state.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock

from database import connect, using_postgres

_SCHEMA_LOCK = Lock()
_SCHEMA_READY = False


@dataclass(frozen=True, slots=True)
class V3ExecutionEventV1:
    request_key: str
    instance_id: str
    account_id: str
    uic: int
    asset_type: str
    market_name: str
    action: str
    side: str
    direction: str
    amount: float
    inventory_before: float
    inventory_after: float
    broker_order_id: str
    executed_at: datetime


def _direction(amount: float) -> str:
    if abs(amount) <= 1e-9:
        return "FLAT"
    return "LONG" if amount > 0 else "SHORT"


def _action(before: float, after: float) -> str:
    if abs(before) <= 1e-9 and abs(after) > 1e-9:
        return "OPEN"
    if abs(after) <= 1e-9 and abs(before) > 1e-9:
        return "CLOSE"
    if before * after < 0:
        return "REVERSE"
    return "ADD" if abs(after) > abs(before) else "REDUCE"


def ensure_v3_execution_event_schema_v1(*, db_path: str = "pricegauger.db") -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    with _SCHEMA_LOCK:
        if _SCHEMA_READY:
            return
        with connect(db_path) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS autotrader_v3_execution_events(
              request_key TEXT PRIMARY KEY,
              instance_id TEXT NOT NULL,
              account_id TEXT NOT NULL,
              uic INTEGER NOT NULL,
              asset_type TEXT NOT NULL,
              market_name TEXT NOT NULL,
              action TEXT NOT NULL,
              side TEXT NOT NULL,
              direction TEXT NOT NULL,
              amount DOUBLE PRECISION NOT NULL,
              inventory_before DOUBLE PRECISION NOT NULL,
              inventory_after DOUBLE PRECISION NOT NULL,
              broker_order_id TEXT NOT NULL,
              executed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
              created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""")
            db.execute("""CREATE INDEX IF NOT EXISTS autotrader_v3_execution_events_market_time_idx
              ON autotrader_v3_execution_events(market_name, executed_at DESC)""")
            # One-time migration of only executions whose old guard proves exact
            # post-order inventory. Inventory-adoption rows are deliberately excluded.
            if using_postgres():
                db.execute("""INSERT INTO autotrader_v3_execution_events(
                  request_key,instance_id,account_id,uic,asset_type,market_name,
                  action,side,direction,amount,inventory_before,inventory_after,
                  broker_order_id,executed_at)
                SELECT g.request_key,g.trader_id,g.account_id,g.uic,g.asset_type,i.market_name,
                  CASE
                    WHEN abs(g.expected_inventory - CASE WHEN lower(g.submitted_side)='buy' THEN g.submitted_amount ELSE -g.submitted_amount END) <= 1e-9 THEN 'OPEN'
                    WHEN abs(g.expected_inventory) <= 1e-9 THEN 'CLOSE'
                    WHEN (g.expected_inventory - CASE WHEN lower(g.submitted_side)='buy' THEN g.submitted_amount ELSE -g.submitted_amount END) * g.expected_inventory < 0 THEN 'REVERSE'
                    WHEN abs(g.expected_inventory) > abs(g.expected_inventory - CASE WHEN lower(g.submitted_side)='buy' THEN g.submitted_amount ELSE -g.submitted_amount END) THEN 'ADD'
                    ELSE 'REDUCE' END,
                  g.submitted_side,
                  CASE WHEN abs(g.expected_inventory)<=1e-9 THEN 'FLAT' WHEN g.expected_inventory>0 THEN 'LONG' ELSE 'SHORT' END,
                  g.submitted_amount,
                  g.expected_inventory - CASE WHEN lower(g.submitted_side)='buy' THEN g.submitted_amount ELSE -g.submitted_amount END,
                  g.expected_inventory,g.broker_order_id,g.updated_at::timestamptz
                FROM autotrader_v3_order_guard g
                JOIN autotrader_v3_engine_instances i
                  ON i.instance_id=g.trader_id AND i.account_id=g.account_id
                 AND i.uic=g.uic AND i.asset_type=g.asset_type
                WHERE g.state='RECONCILED'
                  AND g.broker_order_id IS NOT NULL AND g.broker_order_id<>''
                  AND g.submitted_amount>0
                  AND g.expected_inventory IS NOT NULL
                  AND g.detail='Exact Saxo inventory reached expected post-order position'
                ON CONFLICT(request_key) DO NOTHING""")
        _SCHEMA_READY = True


def record_reconciled_execution_v1(*, request_key: str, instance_id: str,
        account_id: str, uic: int, asset_type: str, market_name: str,
        submitted_side: str, submitted_amount: float, expected_inventory: float,
        broker_order_id: str, db_path: str = "pricegauger.db") -> None:
    """Idempotently persist one execution after exact Saxo inventory confirmation."""
    ensure_v3_execution_event_schema_v1(db_path=db_path)
    amount = float(submitted_amount)
    after = float(expected_inventory)
    signed = amount if str(submitted_side).lower() == "buy" else -amount
    before = after - signed
    with connect(db_path) as db:
        db.execute("""INSERT INTO autotrader_v3_execution_events(
          request_key,instance_id,account_id,uic,asset_type,market_name,
          action,side,direction,amount,inventory_before,inventory_after,broker_order_id,executed_at)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
          ON CONFLICT(request_key) DO NOTHING""",
          (str(request_key),str(instance_id),str(account_id),int(uic),str(asset_type),str(market_name),
           _action(before,after),str(submitted_side),_direction(after),amount,before,after,str(broker_order_id)))


def load_execution_events_v1(market_name: str, *, db_path: str = "pricegauger.db") -> tuple[V3ExecutionEventV1, ...]:
    ensure_v3_execution_event_schema_v1(db_path=db_path)
    with connect(db_path) as db:
        rows=db.execute("""SELECT request_key,instance_id,account_id,uic,asset_type,market_name,
          action,side,direction,amount,inventory_before,inventory_after,broker_order_id,executed_at
          FROM autotrader_v3_execution_events
          WHERE market_name=? AND executed_at >= CURRENT_TIMESTAMP - INTERVAL '14 days'
          ORDER BY executed_at ASC LIMIT 1000""",(str(market_name),)).fetchall()
    result=[]
    for row in rows:
        v=dict(row) if isinstance(row,dict) else {k:row[n] for n,k in enumerate((
            'request_key','instance_id','account_id','uic','asset_type','market_name','action','side','direction','amount','inventory_before','inventory_after','broker_order_id','executed_at'))}
        when=v['executed_at'] if isinstance(v['executed_at'],datetime) else datetime.fromisoformat(str(v['executed_at']).replace('Z','+00:00'))
        if when.tzinfo is None: when=when.replace(tzinfo=timezone.utc)
        result.append(V3ExecutionEventV1(str(v['request_key']),str(v['instance_id']),str(v['account_id']),int(v['uic']),str(v['asset_type']),str(v['market_name']),str(v['action']),str(v['side']),str(v['direction']),float(v['amount']),float(v['inventory_before']),float(v['inventory_after']),str(v['broker_order_id']),when))
    return tuple(result)


__all__=['V3ExecutionEventV1','ensure_v3_execution_event_schema_v1','record_reconciled_execution_v1','load_execution_events_v1']
