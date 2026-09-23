from __future__ import annotations
from database import connect

def ensure_v3_sim_authority_schema(db_path="pricegauger.db"):
    with connect(db_path) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS autotrader_v3_sim_authority (
          trader_id TEXT PRIMARY KEY, armed BOOLEAN NOT NULL DEFAULT FALSE, updated_at TEXT NOT NULL)""")

def sim_authority_armed_v3(trader_id:str, *, db_path="pricegauger.db")->bool:
    ensure_v3_sim_authority_schema(db_path)
    with connect(db_path) as db:
        row=db.execute("SELECT armed FROM autotrader_v3_sim_authority WHERE trader_id=?",(trader_id,)).fetchone()
    return bool(row and (row["armed"] if isinstance(row,dict) else row[0]))

def any_sim_authority_armed_v3(*, db_path="pricegauger.db")->bool:
    ensure_v3_sim_authority_schema(db_path)
    with connect(db_path) as db:
        row=db.execute("SELECT 1 FROM autotrader_v3_sim_authority WHERE armed=TRUE LIMIT 1").fetchone()
    return row is not None

def set_sim_authority_v3(trader_id:str, armed:bool, *, db_path="pricegauger.db")->None:
    ensure_v3_sim_authority_schema(db_path)
    with connect(db_path) as db:
        db.execute("""INSERT INTO autotrader_v3_sim_authority(trader_id,armed,updated_at) VALUES(?,?,CURRENT_TIMESTAMP)
        ON CONFLICT(trader_id) DO UPDATE SET armed=excluded.armed,updated_at=excluded.updated_at""",(trader_id,bool(armed)))
