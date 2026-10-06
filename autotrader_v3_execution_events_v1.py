from __future__ import annotations

"""Canonical durable V3 execution events written atomically with reconciliation."""
from dataclasses import dataclass
from datetime import datetime,timezone
from threading import Lock
from database import connect,using_postgres
_SCHEMA_LOCK=Lock(); _SCHEMA_READY=False

@dataclass(frozen=True,slots=True)
class V3ExecutionEventV1:
    request_key:str; instance_id:str; account_id:str; uic:int; asset_type:str; market_name:str
    action:str; side:str; direction:str; amount:float; inventory_before:float; inventory_after:float
    broker_order_id:str; executed_at:datetime

def ensure_v3_execution_event_schema_v1(*,db_path="pricegauger.db"):
    global _SCHEMA_READY
    if _SCHEMA_READY or not using_postgres(): return
    with _SCHEMA_LOCK:
        if _SCHEMA_READY: return
        with connect(db_path) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS autotrader_v3_execution_events(
              request_key TEXT PRIMARY KEY,instance_id TEXT NOT NULL,account_id TEXT NOT NULL,uic INTEGER NOT NULL,
              asset_type TEXT NOT NULL,market_name TEXT NOT NULL,action TEXT NOT NULL,side TEXT NOT NULL,
              direction TEXT NOT NULL,amount DOUBLE PRECISION NOT NULL,inventory_before DOUBLE PRECISION NOT NULL,
              inventory_after DOUBLE PRECISION NOT NULL,broker_order_id TEXT NOT NULL,
              executed_at TIMESTAMPTZ NOT NULL DEFAULT now(),created_at TIMESTAMPTZ NOT NULL DEFAULT now())""")
            db.execute("""CREATE INDEX IF NOT EXISTS autotrader_v3_execution_events_market_time_idx
              ON autotrader_v3_execution_events(market_name,executed_at DESC)""")
            db.execute("""INSERT INTO autotrader_v3_execution_events(
              request_key,instance_id,account_id,uic,asset_type,market_name,action,side,direction,amount,
              inventory_before,inventory_after,broker_order_id,executed_at)
            SELECT g.request_key,g.trader_id,g.account_id,g.uic,g.asset_type,i.market_name,
              CASE WHEN abs(g.expected_inventory-(CASE WHEN lower(g.submitted_side)='buy' THEN g.submitted_amount ELSE -g.submitted_amount END))<=1e-9 THEN 'OPEN'
                   WHEN abs(g.expected_inventory)<=1e-9 THEN 'CLOSE'
                   WHEN (g.expected_inventory-(CASE WHEN lower(g.submitted_side)='buy' THEN g.submitted_amount ELSE -g.submitted_amount END))*g.expected_inventory<0 THEN 'REVERSE'
                   WHEN abs(g.expected_inventory)>abs(g.expected_inventory-(CASE WHEN lower(g.submitted_side)='buy' THEN g.submitted_amount ELSE -g.submitted_amount END)) THEN 'ADD' ELSE 'REDUCE' END,
              g.submitted_side,CASE WHEN abs(g.expected_inventory)<=1e-9 THEN 'FLAT' WHEN g.expected_inventory>0 THEN 'LONG' ELSE 'SHORT' END,
              g.submitted_amount,g.expected_inventory-(CASE WHEN lower(g.submitted_side)='buy' THEN g.submitted_amount ELSE -g.submitted_amount END),
              g.expected_inventory,g.broker_order_id,g.updated_at::timestamptz
            FROM autotrader_v3_order_guard g JOIN autotrader_v3_engine_instances i
              ON i.instance_id=g.trader_id AND i.account_id=g.account_id AND i.uic=g.uic AND i.asset_type=g.asset_type
            WHERE g.state='RECONCILED' AND g.broker_order_id IS NOT NULL AND g.broker_order_id<>'' AND g.submitted_amount>0
              AND g.expected_inventory IS NOT NULL AND g.detail='Exact Saxo inventory reached expected post-order position'
            ON CONFLICT(request_key) DO NOTHING""")
            db.execute("""CREATE OR REPLACE FUNCTION pg_v3_capture_execution_event() RETURNS trigger AS $$ BEGIN
              IF NEW.state='RECONCILED' AND OLD.state IS DISTINCT FROM 'RECONCILED'
                 AND NEW.detail='Exact Saxo inventory reached expected post-order position'
                 AND NEW.broker_order_id IS NOT NULL AND NEW.submitted_amount>0 AND NEW.expected_inventory IS NOT NULL THEN
                INSERT INTO autotrader_v3_execution_events(request_key,instance_id,account_id,uic,asset_type,market_name,action,side,direction,amount,inventory_before,inventory_after,broker_order_id,executed_at)
                SELECT NEW.request_key,NEW.trader_id,NEW.account_id,NEW.uic,NEW.asset_type,i.market_name,
                  CASE WHEN abs(NEW.expected_inventory-(CASE WHEN lower(NEW.submitted_side)='buy' THEN NEW.submitted_amount ELSE -NEW.submitted_amount END))<=1e-9 THEN 'OPEN'
                       WHEN abs(NEW.expected_inventory)<=1e-9 THEN 'CLOSE'
                       WHEN (NEW.expected_inventory-(CASE WHEN lower(NEW.submitted_side)='buy' THEN NEW.submitted_amount ELSE -NEW.submitted_amount END))*NEW.expected_inventory<0 THEN 'REVERSE'
                       WHEN abs(NEW.expected_inventory)>abs(NEW.expected_inventory-(CASE WHEN lower(NEW.submitted_side)='buy' THEN NEW.submitted_amount ELSE -NEW.submitted_amount END)) THEN 'ADD' ELSE 'REDUCE' END,
                  NEW.submitted_side,CASE WHEN abs(NEW.expected_inventory)<=1e-9 THEN 'FLAT' WHEN NEW.expected_inventory>0 THEN 'LONG' ELSE 'SHORT' END,
                  NEW.submitted_amount,NEW.expected_inventory-(CASE WHEN lower(NEW.submitted_side)='buy' THEN NEW.submitted_amount ELSE -NEW.submitted_amount END),
                  NEW.expected_inventory,NEW.broker_order_id,NEW.updated_at::timestamptz
                FROM autotrader_v3_engine_instances i WHERE i.instance_id=NEW.trader_id AND i.account_id=NEW.account_id AND i.uic=NEW.uic AND i.asset_type=NEW.asset_type
                ON CONFLICT(request_key) DO NOTHING;
              END IF; RETURN NEW; END; $$ LANGUAGE plpgsql""")
            db.execute("DROP TRIGGER IF EXISTS pg_v3_execution_event_trigger ON autotrader_v3_order_guard")
            db.execute("""CREATE TRIGGER pg_v3_execution_event_trigger AFTER UPDATE OF state ON autotrader_v3_order_guard
              FOR EACH ROW EXECUTE FUNCTION pg_v3_capture_execution_event()""")
        _SCHEMA_READY=True

def load_execution_events_v1(market_name:str,*,db_path="pricegauger.db")->tuple[V3ExecutionEventV1,...]:
    ensure_v3_execution_event_schema_v1(db_path=db_path)
    if not using_postgres(): return ()
    with connect(db_path) as db:
        rows=db.execute("""SELECT request_key,instance_id,account_id,uic,asset_type,market_name,action,side,direction,amount,inventory_before,inventory_after,broker_order_id,executed_at
          FROM autotrader_v3_execution_events WHERE market_name=? AND executed_at>=now()-INTERVAL '14 days' ORDER BY executed_at ASC LIMIT 1000""",(str(market_name),)).fetchall()
    keys=('request_key','instance_id','account_id','uic','asset_type','market_name','action','side','direction','amount','inventory_before','inventory_after','broker_order_id','executed_at'); result=[]
    for row in rows:
        v=dict(row) if isinstance(row,dict) else dict(zip(keys,row)); when=v['executed_at'] if isinstance(v['executed_at'],datetime) else datetime.fromisoformat(str(v['executed_at']).replace('Z','+00:00'))
        if when.tzinfo is None: when=when.replace(tzinfo=timezone.utc)
        result.append(V3ExecutionEventV1(str(v['request_key']),str(v['instance_id']),str(v['account_id']),int(v['uic']),str(v['asset_type']),str(v['market_name']),str(v['action']),str(v['side']),str(v['direction']),float(v['amount']),float(v['inventory_before']),float(v['inventory_after']),str(v['broker_order_id']),when))
    return tuple(result)

__all__=['V3ExecutionEventV1','ensure_v3_execution_event_schema_v1','load_execution_events_v1']
