"""Per-instance V3 modifier change-order and read-only operational history.

Telemetry never authorizes broker orders. Timestamp order uses SAVED toggle
changes, not Streamlit rerun times. State changes are one durable record each,
even after worker restart; FLAT requests are not mislabelled broker fills.
"""
from __future__ import annotations

from datetime import datetime, timezone
from database import connect


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def ensure_modifier_audit_schema_v3(db_path="pricegauger.db"):
    with connect(db_path) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS autotrader_v3_modifier_change_order(
          trader_id TEXT NOT NULL,modifier_key TEXT NOT NULL,
          changed_at TEXT NOT NULL,enabled BOOLEAN NOT NULL,
          PRIMARY KEY(trader_id,modifier_key))""")
        db.execute("""CREATE TABLE IF NOT EXISTS autotrader_v3_modifier_live_events(
          id TEXT PRIMARY KEY,trader_id TEXT NOT NULL,modifier_key TEXT NOT NULL,
          observed_at TEXT NOT NULL,event_type TEXT NOT NULL,
          status TEXT NOT NULL,detail TEXT NOT NULL)""")
        db.execute("""CREATE INDEX IF NOT EXISTS pg_v3_modifier_live_events_latest
          ON autotrader_v3_modifier_live_events(trader_id,modifier_key,observed_at DESC)""")


def record_modifier_selection_changes_v3(*,trader_id:str,before,after,db_path="pricegauger.db",at=None):
    from uuid import uuid4
    ensure_modifier_audit_schema_v3(db_path)
    stamp=at or _utc_now()
    events=[]
    for key in sorted(set(before)^set(after)):
        enabled=key in after
        events.append((str(uuid4()),trader_id,key,stamp,"SELECTED",
                       "ON" if enabled else "OFF",
                       "Saved LIVE modifier selection; only LIVE-capable modifiers execute"))
    if not events:return ()
    with connect(db_path) as db:
        for event in events:
            db.execute("""INSERT INTO autotrader_v3_modifier_change_order(
              trader_id,modifier_key,changed_at,enabled) VALUES(?,?,?,?)
              ON CONFLICT(trader_id,modifier_key) DO UPDATE SET
                changed_at=excluded.changed_at,enabled=excluded.enabled""",
               (event[1],event[2],event[3],event[5]=="ON"))
            db.execute("""INSERT INTO autotrader_v3_modifier_live_events(
              id,trader_id,modifier_key,observed_at,event_type,status,detail)
              VALUES(?,?,?,?,?,?,?)""",event)
    return tuple((e[2],e[5]) for e in events)


def sorted_modifiers_by_last_change_v3(trader_id:str,items,*,db_path="pricegauger.db"):
    ensure_modifier_audit_schema_v3(db_path)
    with connect(db_path) as db:
        rows=db.execute("""SELECT modifier_key,changed_at
          FROM autotrader_v3_modifier_change_order WHERE trader_id=?""",
          (trader_id,)).fetchall()
    stamps={str(x["modifier_key"]):str(x["changed_at"]) for x in rows}
    # Most recently explicitly saved button first; stable legacy catalog
    # position for modifiers without a per-button timestamp.
    original={x.key:i for i,x in enumerate(items)}
    return tuple(sorted(items,key=lambda x:(1 if x.key in stamps else 0,
                  stamps.get(x.key,""),-original[x.key]),reverse=True))


def record_modifier_evaluation_v3(*,trader_id:str,modifier_key:str,
                                  status:str,detail:str,now:datetime,
                                  db_path="pricegauger.db"):
    """Emit only on evaluation-status transitions. A FLAT request != a fill."""
    from uuid import uuid4
    ensure_modifier_audit_schema_v3(db_path)
    observed=now.astimezone(timezone.utc).isoformat()
    with connect(db_path) as db:
        latest=db.execute("""SELECT status FROM autotrader_v3_modifier_live_events
           WHERE trader_id=? AND modifier_key=? AND event_type='EVALUATED'
           ORDER BY observed_at DESC LIMIT 1""",(trader_id,modifier_key)).fetchone()
        if latest and str(latest["status"])==status:
            return False
        db.execute("""INSERT INTO autotrader_v3_modifier_live_events
           (id,trader_id,modifier_key,observed_at,event_type,status,detail)
           VALUES(?,?,?,?,?,?,?)""",(
               str(uuid4()),trader_id,modifier_key,observed,"EVALUATED",status,
               detail[:350]))
        return True


def load_modifier_live_events_v3(*,trader_id:str,modifier_key:str,limit:int=25,
                                 db_path="pricegauger.db"):
    ensure_modifier_audit_schema_v3(db_path)
    n=max(1,min(100,int(limit)))
    with connect(db_path) as db:
        rows=db.execute("""SELECT observed_at,event_type,status,detail
          FROM autotrader_v3_modifier_live_events
          WHERE trader_id=? AND modifier_key=?
          ORDER BY observed_at DESC LIMIT ?""",(trader_id,modifier_key,n)).fetchall()
    return tuple(dict(row) for row in rows)
