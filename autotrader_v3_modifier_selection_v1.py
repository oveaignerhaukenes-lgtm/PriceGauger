from __future__ import annotations
from dataclasses import dataclass
from database import connect

@dataclass(frozen=True,slots=True)
class ModifierSelectionV3:
    take_profit: bool=False
    watchdog: bool=False
    overseer: bool=False

def ensure_modifier_schema_v3(db_path="pricegauger.db"):
    with connect(db_path) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS autotrader_v3_modifier_selection(
          trader_id TEXT PRIMARY KEY,take_profit BOOLEAN NOT NULL DEFAULT FALSE,
          watchdog BOOLEAN NOT NULL DEFAULT FALSE,overseer BOOLEAN NOT NULL DEFAULT FALSE,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")

def load_modifier_selection_v3(trader_id,db_path="pricegauger.db"):
    ensure_modifier_schema_v3(db_path)
    with connect(db_path) as db:
        row=db.execute("SELECT take_profit,watchdog,overseer FROM autotrader_v3_modifier_selection WHERE trader_id=?",(trader_id,)).fetchone()
    if row is None:return ModifierSelectionV3()
    get=lambda k,i: row[k] if isinstance(row,dict) else row[i]
    return ModifierSelectionV3(bool(get("take_profit",0)),bool(get("watchdog",1)),bool(get("overseer",2)))

def save_modifier_selection_v3(trader_id,selection,db_path="pricegauger.db"):
    ensure_modifier_schema_v3(db_path)
    with connect(db_path) as db:
        db.execute("""INSERT INTO autotrader_v3_modifier_selection(trader_id,take_profit,watchdog,overseer,updated_at)
        VALUES(?,?,?,?,CURRENT_TIMESTAMP) ON CONFLICT(trader_id) DO UPDATE SET take_profit=excluded.take_profit,
        watchdog=excluded.watchdog,overseer=excluded.overseer,updated_at=excluded.updated_at""",
        (trader_id,selection.take_profit,selection.watchdog,selection.overseer))
    return selection
