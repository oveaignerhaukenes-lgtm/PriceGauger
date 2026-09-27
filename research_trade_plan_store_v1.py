from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4
from database import connect

VALID_PLAN_STATUSES = {"DRAFT", "APPROVED", "CANCELLED", "CLOSED"}
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

def create_research_trade_plan_v1(*, strategy_key: str, hypothesis_version: int,
                                  instrument_label: str, direction: str,
                                  probability_pct: float, capital_pct: float,
                                  stop_loss_pct: float, trail_activation_pct: float,
                                  trailing_distance_pct: float, event_policy: str,
                                  rationale: str) -> str:
    direction = str(direction).upper()
    if direction not in VALID_DIRECTIONS:
        raise ValueError("direction must be LONG or SHORT")
    for label, value in (("probability_pct", probability_pct), ("capital_pct", capital_pct)):
        if not 0 < float(value) <= 100:
            raise ValueError(f"{label} must be in (0, 100]")
    for label, value in (("stop_loss_pct", stop_loss_pct), ("trail_activation_pct", trail_activation_pct),
                         ("trailing_distance_pct", trailing_distance_pct)):
        if float(value) <= 0:
            raise ValueError(f"{label} must be positive")
    plan_id = str(uuid4())
    with connect() as db:
        ensure_research_trade_plan_schema_v1()
        db.execute("""INSERT INTO pg_v2_research_trade_plans(
            plan_id,strategy_key,hypothesis_version,status,instrument_label,direction,
            probability_pct,capital_pct,stop_loss_pct,trail_activation_pct,
            trailing_distance_pct,event_policy,rationale,created_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (plan_id,strategy_key,int(hypothesis_version),"DRAFT",instrument_label.strip(),direction,
         float(probability_pct),float(capital_pct),float(stop_loss_pct),
         float(trail_activation_pct),float(trailing_distance_pct),event_policy.strip(),
         rationale.strip(),datetime.now(timezone.utc)))
    return plan_id

def load_research_trade_plans_v1(strategy_key: str) -> tuple[ResearchTradePlanV1, ...]:
    ensure_research_trade_plan_schema_v1()
    with connect() as db:
        rows=db.execute("""SELECT * FROM pg_v2_research_trade_plans
                           WHERE strategy_key=? ORDER BY created_at DESC""",(strategy_key,)).fetchall()
    return tuple(ResearchTradePlanV1(**dict(row)) for row in rows)
