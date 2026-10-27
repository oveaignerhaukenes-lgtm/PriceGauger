"""Small durable per-V3-modifier event history and chronologically sorted control UI.

Logs signal / permitted-target proposals, not unconfirmed Saxo fills.
Existing execution-events ledger is the authoritative source of broker fills.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4
from database import connect

SAFETY_MODIFIERS=frozenset({"impulse-exit","account-loss-lock"})


def ensure_modifier_log_schema_v3(db_path="pricegauger.db"):
    with connect(db_path) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS autotrader_v3_modifier_log(
          event_id TEXT PRIMARY KEY, trader_id TEXT NOT NULL,
          modifier_key TEXT NOT NULL, event_type TEXT NOT NULL,
          state TEXT NOT NULL, detail TEXT NOT NULL,
          event_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
        db.execute("""CREATE INDEX IF NOT EXISTS av3_modifier_log_last
          ON autotrader_v3_modifier_log(trader_id,modifier_key,event_at DESC)""")


def record_modifier_event_v3(*,trader_id,modifier_key,event_type,state,detail,
                             db_path="pricegauger.db"):
    ensure_modifier_log_schema_v3(db_path)
    with connect(db_path) as db:
        db.execute("""INSERT INTO autotrader_v3_modifier_log(
            event_id,trader_id,modifier_key,event_type,state,detail,event_at)
            VALUES(?,?,?,?,?,?,CURRENT_TIMESTAMP)""",
            (str(uuid4()),str(trader_id),str(modifier_key),
             str(event_type)[:50],str(state)[:50],str(detail)[:420]))


def record_modifier_selection_changes_v3(*,trader_id,previous,selected,
                                         db_path="pricegauger.db"):
    before=set(previous); after=set(selected)
    for key in sorted(before^after):
        enabled=key in after
        record_modifier_event_v3(
            trader_id=trader_id,modifier_key=key,event_type="CONFIG_CHANGED",
            state="ON" if enabled else "OFF",
            detail="LIVE/SIM instance configuration selection; not proof of broker execution",
            db_path=db_path
        )


def modifier_recent_changes_v3(trader_id,db_path="pricegauger.db")->dict:
    ensure_modifier_log_schema_v3(db_path)
    with connect(db_path) as db:
        rows=db.execute("""SELECT modifier_key,MAX(event_at) AS changed_at
          FROM autotrader_v3_modifier_log
          WHERE trader_id=? AND event_type='CONFIG_CHANGED'
          GROUP BY modifier_key""",(str(trader_id),)).fetchall()
    return {str(r["modifier_key"]):str(r["changed_at"]) for r in rows}


def load_modifier_log_v3(trader_id,modifier_key,*,limit=30,db_path="pricegauger.db"):
    ensure_modifier_log_schema_v3(db_path)
    with connect(db_path) as db:
        rows=db.execute("""SELECT event_type,state,detail,event_at
          FROM autotrader_v3_modifier_log
          WHERE trader_id=? AND modifier_key=?
          ORDER BY event_at DESC LIMIT ?""",
          (str(trader_id),str(modifier_key),min(80,max(1,int(limit))))).fetchall()
    return tuple(dict(r) for r in rows)
