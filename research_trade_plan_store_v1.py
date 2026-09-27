from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from uuid import uuid4
from database import connect

VALID_DIRECTIONS={"LONG","SHORT"}

@dataclass(frozen=True,slots=True)
class ResearchTradePlanV1:
    plan_id:str; strategy_key:str; hypothesis_version:int; status:str
    instrument_label:str; direction:str; probability_pct:float; capital_pct:float
    budget_nok:float; exposure_pct:float; stop_loss_pct:float
    trail_activation_pct:float; trailing_distance_pct:float
    event_policy:str; rationale:str; created_at:datetime

@dataclass(frozen=True,slots=True)
class ResearchExecutionHandoffV1:
    handoff_id:str; plan_id:str; strategy_key:str; scope_id:str
    status:str; payload_json:str; approved_at:datetime
    queued_at:datetime|None; created_at:datetime

def execution_scope_id_v1(*,strategy_key:str,plan_id:str)->str:
    strategy=str(strategy_key).strip()
    plan=str(plan_id).strip()
    if not strategy or not plan: raise ValueError("strategy_key and plan_id are required")
    return f"{strategy}:{plan}"

def ensure_research_trade_plan_schema_v1()->None:
    with connect() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS pg_v2_research_trade_plans(
          plan_id TEXT PRIMARY KEY,strategy_key TEXT NOT NULL,hypothesis_version INTEGER NOT NULL,
          status TEXT NOT NULL,instrument_label TEXT NOT NULL,direction TEXT NOT NULL,
          probability_pct DOUBLE PRECISION NOT NULL,capital_pct DOUBLE PRECISION NOT NULL,
          budget_nok DOUBLE PRECISION NOT NULL DEFAULT 2000,exposure_pct DOUBLE PRECISION NOT NULL DEFAULT 100,
          stop_loss_pct DOUBLE PRECISION NOT NULL,trail_activation_pct DOUBLE PRECISION NOT NULL,
          trailing_distance_pct DOUBLE PRECISION NOT NULL,event_policy TEXT NOT NULL,
          rationale TEXT NOT NULL,created_at TIMESTAMPTZ NOT NULL)""")
        db.execute("ALTER TABLE pg_v2_research_trade_plans ADD COLUMN IF NOT EXISTS budget_nok DOUBLE PRECISION NOT NULL DEFAULT 2000")
        db.execute("ALTER TABLE pg_v2_research_trade_plans ADD COLUMN IF NOT EXISTS exposure_pct DOUBLE PRECISION NOT NULL DEFAULT 100")
        db.execute("""CREATE TABLE IF NOT EXISTS pg_v2_research_execution_handoffs(
          handoff_id TEXT PRIMARY KEY,plan_id TEXT NOT NULL UNIQUE,strategy_key TEXT NOT NULL,
          scope_id TEXT,status TEXT NOT NULL,payload_json TEXT NOT NULL,approved_at TIMESTAMPTZ NOT NULL,
          queued_at TIMESTAMPTZ,created_at TIMESTAMPTZ NOT NULL)""")
        db.execute("ALTER TABLE pg_v2_research_execution_handoffs ADD COLUMN IF NOT EXISTS scope_id TEXT")
        db.execute("""UPDATE pg_v2_research_execution_handoffs
                      SET scope_id=strategy_key || ':' || plan_id
                      WHERE scope_id IS NULL OR scope_id=''""")

def create_research_trade_plan_v1(*,strategy_key:str,hypothesis_version:int,instrument_label:str,
 direction:str,probability_pct:float,capital_pct:float,budget_nok:float,exposure_pct:float,
 stop_loss_pct:float,trail_activation_pct:float,trailing_distance_pct:float,event_policy:str,rationale:str)->str:
    direction=str(direction).upper()
    if direction not in VALID_DIRECTIONS: raise ValueError("direction must be LONG or SHORT")
    for label,value in (("probability_pct",probability_pct),("capital_pct",capital_pct)):
        if not 0<float(value)<=100: raise ValueError(f"{label} must be in (0,100]")
    if not 0<=float(exposure_pct)<=100: raise ValueError("exposure_pct must be in [0,100]")
    if float(budget_nok)<=0: raise ValueError("budget_nok must be positive")
    for label,value in (("stop_loss_pct",stop_loss_pct),("trail_activation_pct",trail_activation_pct),("trailing_distance_pct",trailing_distance_pct)):
        if float(value)<=0: raise ValueError(f"{label} must be positive")
    plan_id=str(uuid4()); ensure_research_trade_plan_schema_v1()
    with connect() as db:
        db.execute("""INSERT INTO pg_v2_research_trade_plans(
          plan_id,strategy_key,hypothesis_version,status,instrument_label,direction,probability_pct,
          capital_pct,budget_nok,exposure_pct,stop_loss_pct,trail_activation_pct,trailing_distance_pct,
          event_policy,rationale,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
          (plan_id,strategy_key,int(hypothesis_version),"DRAFT",instrument_label.strip(),direction,
           float(probability_pct),float(capital_pct),float(budget_nok),float(exposure_pct),
           float(stop_loss_pct),float(trail_activation_pct),float(trailing_distance_pct),
           event_policy.strip(),rationale.strip(),datetime.now(timezone.utc)))
    return plan_id

def load_research_trade_plans_v1(strategy_key:str)->tuple[ResearchTradePlanV1,...]:
    ensure_research_trade_plan_schema_v1()
    with connect() as db:
        rows=db.execute("SELECT * FROM pg_v2_research_trade_plans WHERE strategy_key=? ORDER BY created_at DESC",(strategy_key,)).fetchall()
    return tuple(ResearchTradePlanV1(**dict(r)) for r in rows)

def approve_research_trade_plan_v1(plan_id:str)->str:
    ensure_research_trade_plan_schema_v1(); now=datetime.now(timezone.utc)
    with connect() as db:
        row=db.execute("SELECT * FROM pg_v2_research_trade_plans WHERE plan_id=?",(plan_id,)).fetchone()
        if row is None: raise ValueError("trade plan not found")
        p=dict(row)
        if p["status"]!="DRAFT": raise ValueError("only DRAFT plans can be approved")
        scope=execution_scope_id_v1(strategy_key=p["strategy_key"],plan_id=p["plan_id"])
        payload={k:p[k] for k in ("plan_id","strategy_key","hypothesis_version","instrument_label","direction",
          "probability_pct","capital_pct","budget_nok","exposure_pct","stop_loss_pct",
          "trail_activation_pct","trailing_distance_pct","event_policy","rationale")}
        payload["scope_id"]=scope
        handoff=str(uuid4())
        db.execute("""INSERT INTO pg_v2_research_execution_handoffs(
          handoff_id,plan_id,strategy_key,scope_id,status,payload_json,approved_at,queued_at,created_at)
          VALUES(?,?,?,?,?,?,?,?,?)""",(handoff,plan_id,p["strategy_key"],scope,"APPROVED",json.dumps(payload,sort_keys=True),now,None,now))
        db.execute("UPDATE pg_v2_research_trade_plans SET status='APPROVED' WHERE plan_id=?",(plan_id,))
    return handoff

def load_research_execution_handoff_v1(plan_id:str)->ResearchExecutionHandoffV1|None:
    ensure_research_trade_plan_schema_v1()
    with connect() as db: row=db.execute("SELECT * FROM pg_v2_research_execution_handoffs WHERE plan_id=?",(plan_id,)).fetchone()
    return None if row is None else ResearchExecutionHandoffV1(**dict(row))

def assert_research_scope_v1(*,plan_id:str,strategy_key:str,scope_id:str)->ResearchExecutionHandoffV1:
    handoff=load_research_execution_handoff_v1(plan_id)
    expected=execution_scope_id_v1(strategy_key=strategy_key,plan_id=plan_id)
    if handoff is None or handoff.strategy_key!=strategy_key or handoff.scope_id!=expected or scope_id!=expected:
        raise ValueError("RESEARCH_EXECUTION_SCOPE_MISMATCH")
    return handoff

def mark_research_handoff_queued_v1(plan_id:str)->None:
    ensure_research_trade_plan_schema_v1(); now=datetime.now(timezone.utc)
    with connect() as db:
        row=db.execute("SELECT status FROM pg_v2_research_execution_handoffs WHERE plan_id=?",(plan_id,)).fetchone()
        if row is None or str(row[0] if not isinstance(row,dict) else row["status"])!="APPROVED": raise ValueError("handoff must be APPROVED before queueing")
        db.execute("UPDATE pg_v2_research_execution_handoffs SET status='QUEUED',queued_at=? WHERE plan_id=?",(now,plan_id))
        db.execute("UPDATE pg_v2_research_trade_plans SET status='QUEUED' WHERE plan_id=?",(plan_id,))
