from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from uuid import uuid4
from database import connect

VALID_PLAN_STATUSES = {"DRAFT", "APPROVED", "QUEUED", "CANCELLED", "CLOSED"}
VALID_DIRECTIONS = {"LONG", "SHORT"}

@dataclass(frozen=True, slots=True)
class ResearchTradePlanV1:
    plan_id: str
    strategy_key: str
    hypothesis_version: int
    status: str
    instrument_label: str
    direction: str
    probability_pct: float
    capital_pct: float
    stop_loss_pct: float
    trail_activation_pct: float
    trailing_distance_pct: float
    event_policy: str
    rationale: str
    created_at: datetime

@dataclass(frozen=True, slots=True)
class ResearchExecutionHandoffV1:
    handoff_id: str
    plan_id: str
    strategy_key: str
    status: str
    payload_json: str
    approved_at: datetime
    queued_at: datetime | None
    created_at: datetime

def ensure_research_trade_plan_schema_v1() -> None:
    with connect() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS pg_v2_research_trade_plans (
                plan_id TEXT PRIMARY KEY,
                strategy_key TEXT NOT NULL,
                hypothesis_version INTEGER NOT NULL,
                status TEXT NOT NULL,
                instrument_label TEXT NOT NULL,
                direction TEXT NOT NULL,
                probability_pct DOUBLE PRECISION NOT NULL,
                capital_pct DOUBLE PRECISION NOT NULL,
                stop_loss_pct DOUBLE PRECISION NOT NULL,
                trail_activation_pct DOUBLE PRECISION NOT NULL,
                trailing_distance_pct DOUBLE PRECISION NOT NULL,
                event_policy TEXT NOT NULL,
                rationale TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS pg_v2_research_execution_handoffs (
                handoff_id TEXT PRIMARY KEY,
                plan_id TEXT NOT NULL UNIQUE,
                strategy_key TEXT NOT NULL,
                status TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                approved_at TIMESTAMPTZ NOT NULL,
                queued_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL
            )
        """)

def create_research_trade_plan_v1(*, strategy_key: str, hypothesis_version: int,
                                  instrument_label: str, direction: str,
                                  probability_pct: float, capital_pct: float,
                                  stop_loss_pct: float, trail_activation_pct: float,
                                  trailing_distance_pct: float, event_policy: str,
                                  rationale: str) -> str:
    direction = str(direction).upper()
    if direction not in VALID_DIRECTIONS:
        raise ValueError("direction must be LONG or SHORT")
    for label, value in (("probability_pct", probability_pct), ("capital_pct", capital_pct), ("exposure_pct", exposure_pct)):
        if not 0 < float(value) <= 100:
            raise ValueError(f"{label} must be in (0, 100]")
    if float(budget_nok) <= 0:\n        raise ValueError("budget_nok must be positive")\n    for label, value in (("stop_loss_pct", stop_loss_pct), ("trail_activation_pct", trail_activation_pct),
                         ("trailing_distance_pct", trailing_distance_pct)):
        if float(value) <= 0:
            raise ValueError(f"{label} must be positive")
    plan_id = str(uuid4())
    ensure_research_trade_plan_schema_v1()
    with connect() as db:
        db.execute("""INSERT INTO pg_v2_research_trade_plans(
            plan_id,strategy_key,hypothesis_version,status,instrument_label,direction,
            probability_pct,capital_pct,budget_nok,exposure_pct,stop_loss_pct,trail_activation_pct,
            trailing_distance_pct,event_policy,rationale,created_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (plan_id,strategy_key,int(hypothesis_version),"DRAFT",instrument_label.strip(),direction,
         float(probability_pct),float(capital_pct),float(budget_nok),float(exposure_pct),float(stop_loss_pct),
         float(trail_activation_pct),float(trailing_distance_pct),event_policy.strip(),
         rationale.strip(),datetime.now(timezone.utc)))
    return plan_id

def load_research_trade_plans_v1(strategy_key: str) -> tuple[ResearchTradePlanV1, ...]:
    ensure_research_trade_plan_schema_v1()
    with connect() as db:
        rows=db.execute("""SELECT * FROM pg_v2_research_trade_plans
                           WHERE strategy_key=? ORDER BY created_at DESC""",(strategy_key,)).fetchall()
    return tuple(ResearchTradePlanV1(**dict(row)) for row in rows)

def approve_research_trade_plan_v1(plan_id: str) -> str:
    """Freeze an explicit research plan into an auditable execution handoff.

    Approval does not POST to a broker and does not create a live execution request.
    The execution adapter must validate product/account identity and route the frozen
    payload through the existing hardened durable execution lifecycle.
    """
    ensure_research_trade_plan_schema_v1()
    now=datetime.now(timezone.utc)
    with connect() as db:
        row=db.execute("SELECT * FROM pg_v2_research_trade_plans WHERE plan_id=?",(plan_id,)).fetchone()
        if row is None:
            raise ValueError("trade plan not found")
        plan=dict(row)
        if str(plan["status"]) != "DRAFT":
            raise ValueError("only DRAFT plans can be approved")
        payload={k: plan[k] for k in (
            "plan_id","strategy_key","hypothesis_version","instrument_label","direction",
            "probability_pct","capital_pct","budget_nok","exposure_pct","stop_loss_pct","trail_activation_pct",
            "trailing_distance_pct","event_policy","rationale"
        )}
        handoff_id=str(uuid4())
        db.execute("""INSERT INTO pg_v2_research_execution_handoffs(
            handoff_id,plan_id,strategy_key,status,payload_json,approved_at,queued_at,created_at
        ) VALUES (?,?,?,?,?,?,?,?)""",
        (handoff_id,plan_id,plan["strategy_key"],"APPROVED",json.dumps(payload,sort_keys=True),
         now,None,now))
        db.execute("UPDATE pg_v2_research_trade_plans SET status='APPROVED' WHERE plan_id=?",(plan_id,))
    return handoff_id

def load_research_execution_handoff_v1(plan_id: str) -> ResearchExecutionHandoffV1 | None:
    ensure_research_trade_plan_schema_v1()
    with connect() as db:
        row=db.execute("SELECT * FROM pg_v2_research_execution_handoffs WHERE plan_id=?",(plan_id,)).fetchone()
    return None if row is None else ResearchExecutionHandoffV1(**dict(row))

def mark_research_handoff_queued_v1(plan_id: str) -> None:
    """Mark adapter acceptance only; broker execution remains downstream."""
    ensure_research_trade_plan_schema_v1()
    now=datetime.now(timezone.utc)
    with connect() as db:
        row=db.execute("SELECT status FROM pg_v2_research_execution_handoffs WHERE plan_id=?",(plan_id,)).fetchone()
        if row is None or str(row[0] if not isinstance(row,dict) else row["status"]) != "APPROVED":
            raise ValueError("handoff must be APPROVED before queueing")
        db.execute("UPDATE pg_v2_research_execution_handoffs SET status='QUEUED',queued_at=? WHERE plan_id=?",(now,plan_id))
        db.execute("UPDATE pg_v2_research_trade_plans SET status='QUEUED' WHERE plan_id=?",(plan_id,))
