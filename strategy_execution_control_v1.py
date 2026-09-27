from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4
from database import connect

VALID_ACTIONS={"CLOSE","TRAILING_PROFIT","SCALE_DOWN","STOP_LOSS"}

@dataclass(frozen=True,slots=True)
class StrategyExecutionControlV1:
    control_id:str
    plan_id:str
    action:str
    value_pct:float|None
    status:str
    created_at:datetime

def ensure_strategy_execution_control_schema_v1()->None:
    with connect() as db:
        db.execute("""
        CREATE TABLE IF NOT EXISTS pg_v2_strategy_execution_controls(
          control_id TEXT PRIMARY KEY, plan_id TEXT NOT NULL, action TEXT NOT NULL,
          value_pct DOUBLE PRECISION, status TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL
        )""")

def request_strategy_execution_control_v1(*,plan_id:str,action:str,value_pct:float|None=None)->str:
    """Persist an explicit management intent. This function never POSTs to Saxo."""
    action=str(action).upper()
    if action not in VALID_ACTIONS: raise ValueError("unsupported execution control")
    if action!="CLOSE" and (value_pct is None or not 0<float(value_pct)<=100):
        raise ValueError("value_pct must be in (0,100]")
    ensure_strategy_execution_control_schema_v1()
    control_id=str(uuid4())
    with connect() as db:
        handoff=db.execute("SELECT status FROM pg_v2_research_execution_handoffs WHERE plan_id=?",(plan_id,)).fetchone()
        if handoff is None or str(handoff[0] if not isinstance(handoff,dict) else handoff["status"]) not in {"APPROVED","QUEUED"}:
            raise ValueError("execution controls require an approved plan")
        db.execute("INSERT INTO pg_v2_strategy_execution_controls(control_id,plan_id,action,value_pct,status,created_at) VALUES(?,?,?,?,?,?)",
                   (control_id,plan_id,action,value_pct,"PENDING",datetime.now(timezone.utc)))
    return control_id

def load_strategy_execution_controls_v1(plan_id:str)->tuple[StrategyExecutionControlV1,...]:
    ensure_strategy_execution_control_schema_v1()
    with connect() as db:
        rows=db.execute("SELECT * FROM pg_v2_strategy_execution_controls WHERE plan_id=? ORDER BY created_at DESC",(plan_id,)).fetchall()
    return tuple(StrategyExecutionControlV1(**dict(r)) for r in rows)
