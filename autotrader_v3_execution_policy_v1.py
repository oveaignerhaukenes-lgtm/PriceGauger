"""Persistent V3 submission-time exposure policy.

Budget is a maximum position notional in NOK at submission time. Later market/FX
movement does not retroactively invalidate a position.
"""
from __future__ import annotations
from dataclasses import dataclass
from math import isfinite
from database import connect

@dataclass(frozen=True, slots=True)
class ExecutionPolicyV3:
    trader_id: str
    budget_nok: float
    exposure_pct: float

    def __post_init__(self):
        if not self.trader_id.strip(): raise ValueError('trader_id required')
        if not isfinite(float(self.budget_nok)) or float(self.budget_nok)<=0: raise ValueError('budget_nok must be positive')
        if not isfinite(float(self.exposure_pct)) or not 0<float(self.exposure_pct)<=100: raise ValueError('exposure_pct must be 0..100')
    @property
    def max_notional_nok(self)->float:
        return float(self.budget_nok)*float(self.exposure_pct)/100.0

def ensure_schema(db_path='pricegauger.db'):
    with connect(db_path) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS autotrader_v3_execution_policy(
          trader_id TEXT PRIMARY KEY,budget_nok REAL NOT NULL,exposure_pct REAL NOT NULL,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")

def load_execution_policy_v3(trader_id:str,*,db_path='pricegauger.db')->ExecutionPolicyV3|None:
    ensure_schema(db_path)
    with connect(db_path) as db:
        row=db.execute('SELECT budget_nok,exposure_pct FROM autotrader_v3_execution_policy WHERE trader_id=?',(trader_id,)).fetchone()
    if row is None:return None
    return ExecutionPolicyV3(trader_id,float(row['budget_nok'] if isinstance(row,dict) else row[0]),float(row['exposure_pct'] if isinstance(row,dict) else row[1]))

def save_execution_policy_v3(policy:ExecutionPolicyV3,*,db_path='pricegauger.db'):
    ensure_schema(db_path)
    with connect(db_path) as db:
        db.execute("""INSERT INTO autotrader_v3_execution_policy(trader_id,budget_nok,exposure_pct,updated_at)
        VALUES(?,?,?,CURRENT_TIMESTAMP) ON CONFLICT(trader_id) DO UPDATE SET
        budget_nok=excluded.budget_nok,exposure_pct=excluded.exposure_pct,updated_at=excluded.updated_at""",
        (policy.trader_id,policy.budget_nok,policy.exposure_pct))
