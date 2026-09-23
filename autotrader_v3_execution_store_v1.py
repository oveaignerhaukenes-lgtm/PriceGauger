from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from database import connect

@dataclass(frozen=True, slots=True)
class DurableIntentV3:
    intent_id: str
    decision_key: str
    status: str
    created_at: str
    payload_json: str

def ensure_v3_execution_schema(db_path="pricegauger.db"):
    with connect(db_path) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS autotrader_v3_execution_intents (
          intent_id TEXT PRIMARY KEY, decision_key TEXT NOT NULL, status TEXT NOT NULL,
          created_at TEXT NOT NULL, payload_json TEXT NOT NULL)""")
        conn.commit()

def reserve_intent_v3(*, intent_id:str, decision_key:str, payload:dict, db_path="pricegauger.db")->bool:
    ensure_v3_execution_schema(db_path)
    now=datetime.now(timezone.utc).isoformat()
    with connect(db_path) as conn:
        cur=conn.execute("""INSERT INTO autotrader_v3_execution_intents(intent_id,decision_key,status,created_at,payload_json)
        VALUES(?,?,?,?,?) ON CONFLICT(intent_id) DO NOTHING""",(intent_id,decision_key,"RESERVED",now,json.dumps(payload,sort_keys=True)))
        conn.commit()
        return cur.rowcount==1

def mark_intent_attempted_v3(intent_id:str, *, db_path="pricegauger.db"):
    ensure_v3_execution_schema(db_path)
    with connect(db_path) as conn:
        conn.execute("UPDATE autotrader_v3_execution_intents SET status='ATTEMPTED' WHERE intent_id=?",(intent_id,))
        conn.commit()

def intent_status_v3(intent_id:str, *, db_path="pricegauger.db")->str|None:
    ensure_v3_execution_schema(db_path)
    with connect(db_path) as conn:
        row=conn.execute("SELECT status FROM autotrader_v3_execution_intents WHERE intent_id=?",(intent_id,)).fetchone()
    return None if row is None else str(row[0])
