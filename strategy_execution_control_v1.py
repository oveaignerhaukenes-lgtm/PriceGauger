from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime,timezone
from uuid import uuid4
from database import connect
from research_trade_plan_store_v1 import assert_research_scope_v1

VALID_ACTIONS={"CLOSE","TRAILING_PROFIT","SCALE_DOWN","STOP_LOSS"}

@dataclass(frozen=True,slots=True)
class StrategyExecutionControlV1:
    control_id:str; plan_id:str; strategy_key:str; scope_id:str
    action:str; value_pct:float|None; status:str; created_at:datetime
    request_id:str|None=None; block_reason:str|None=None

def ensure_strategy_execution_control_schema_v1()->None:
    with connect() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS pg_v2_strategy_execution_controls(
          control_id TEXT PRIMARY KEY,plan_id TEXT NOT NULL,strategy_key TEXT,scope_id TEXT,
          action TEXT NOT NULL,value_pct DOUBLE PRECISION,status TEXT NOT NULL,created_at TIMESTAMPTZ NOT NULL)""")
        db.execute("ALTER TABLE pg_v2_strategy_execution_controls ADD COLUMN IF NOT EXISTS strategy_key TEXT")
        db.execute("ALTER TABLE pg_v2_strategy_execution_controls ADD COLUMN IF NOT EXISTS scope_id TEXT")
        db.execute("ALTER TABLE pg_v2_strategy_execution_controls ADD COLUMN IF NOT EXISTS request_id UUID")
        db.execute("ALTER TABLE pg_v2_strategy_execution_controls ADD COLUMN IF NOT EXISTS block_reason TEXT")

def request_strategy_execution_control_v1(*,plan_id:str,strategy_key:str,scope_id:str,action:str,value_pct:float|None=None)->str:
    """Persist only an intent whose complete Strategy Lab scope still matches."""
    action=str(action).upper()
    if action not in VALID_ACTIONS: raise ValueError("unsupported execution control")
    if action!="CLOSE" and (value_pct is None or not 0<float(value_pct)<=100): raise ValueError("value_pct must be in (0,100]")
    handoff=assert_research_scope_v1(plan_id=plan_id,strategy_key=strategy_key,scope_id=scope_id)
    if handoff.status not in {"APPROVED","QUEUED"}: raise ValueError("execution controls require an approved plan")
    ensure_strategy_execution_control_schema_v1(); control_id=str(uuid4())
    with connect() as db:
        db.execute("""INSERT INTO pg_v2_strategy_execution_controls(
          control_id,plan_id,strategy_key,scope_id,action,value_pct,status,created_at)
          VALUES(?,?,?,?,?,?,?,?)""",(control_id,plan_id,strategy_key,scope_id,action,value_pct,"PENDING",datetime.now(timezone.utc)))
    return control_id

def load_strategy_execution_controls_v1(*,plan_id:str,strategy_key:str,scope_id:str)->tuple[StrategyExecutionControlV1,...]:
    assert_research_scope_v1(plan_id=plan_id,strategy_key=strategy_key,scope_id=scope_id)
    ensure_strategy_execution_control_schema_v1()
    with connect() as db:
        rows=db.execute("""SELECT * FROM pg_v2_strategy_execution_controls
          WHERE plan_id=? AND strategy_key=? AND scope_id=? ORDER BY created_at DESC""",(plan_id,strategy_key,scope_id)).fetchall()
    return tuple(StrategyExecutionControlV1(**{k:dict(r)[k] for k in StrategyExecutionControlV1.__dataclass_fields__ if k in dict(r)}) for r in rows)
