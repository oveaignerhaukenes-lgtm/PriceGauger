"""Durable per-strategy V3 STOP/GO latch; no automatic model decisions yet.

STOP vetoes only OPEN/ADD. An already held position must still be able to
REDUCE/CLOSE using the existing Saxo ownership, precheck and order guards.
The latch is checked again *after* reservation, immediately before Saxo POST,
so a STOP set during a slow Saxo precheck cannot leak an entry.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from database import connect, run_postgres_schema_once_v1


@dataclass(frozen=True, slots=True)
class V3TradeFilterV1:
    instance_id: str
    strategy_key: str
    mode: str
    source: str
    updated_at: str | None


def ensure_trade_filter_schema_v1(db_path="pricegauger.db") -> None:
    def initialize():
        with connect(db_path) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS pg_v3_trade_filter_control_v1(
                instance_id TEXT PRIMARY KEY,
                strategy_key TEXT NOT NULL,
                mode TEXT NOT NULL CHECK(mode IN ('GO','STOP')),
                source TEXT NOT NULL CHECK(source IN ('OPERATOR','VALIDATED_MODEL')),
                updated_at TEXT NOT NULL)""")
    run_postgres_schema_once_v1("v3_trade_filter_control_v1", initialize)


def load_trade_filter_v1(*,instance_id:str,strategy_key:str,
                         db_path="pricegauger.db") -> V3TradeFilterV1:
    """GO by default; an unreadable latch raises rather than clearing STOP."""
    identity=str(instance_id or "").strip()
    strategy=str(strategy_key or "").strip()
    if not identity or not strategy:
        raise ValueError("exact V3 instance and strategy required")
    ensure_trade_filter_schema_v1(db_path)
    with connect(db_path) as db:
        row=db.execute("""SELECT instance_id,strategy_key,mode,source,updated_at
            FROM pg_v3_trade_filter_control_v1 WHERE instance_id=?""",
            (identity,)).fetchone()
    if row is None or str(row["strategy_key"])!=strategy:
        return V3TradeFilterV1(identity,strategy,"GO","DEFAULT",None)
    mode=str(row["mode"])
    if mode not in ("GO","STOP"):
        raise ValueError("unrecognized filter mode")
    return V3TradeFilterV1(identity,strategy,mode,
                           str(row["source"]),str(row["updated_at"]))


def set_trade_filter_v1(*,instance_id:str,strategy_key:str,mode:str,
                        source:str="OPERATOR",db_path="pricegauger.db") -> V3TradeFilterV1:
    """Explicit operator action; the research observer never calls this."""
    if mode not in ("GO","STOP"):
        raise ValueError("mode must be GO or STOP")
    if source != "OPERATOR":
        raise ValueError("automatic LIVE gating is not yet approved")
    identity=str(instance_id or "").strip()
    strategy=str(strategy_key or "").strip()
    if not identity or not strategy:
        raise ValueError("exact V3 instance and strategy required")
    ensure_trade_filter_schema_v1(db_path)
    now=datetime.now(timezone.utc).isoformat()
    with connect(db_path) as db:
        db.execute("""INSERT INTO pg_v3_trade_filter_control_v1(
            instance_id,strategy_key,mode,source,updated_at)
            VALUES(?,?,?,?,?) ON CONFLICT(instance_id) DO UPDATE SET
            strategy_key=excluded.strategy_key,mode=excluded.mode,
            source=excluded.source,updated_at=excluded.updated_at""",
            (identity,strategy,mode,source,now))
    return V3TradeFilterV1(identity,strategy,mode,source,now)


def allow_new_exposure_v1(*,instance_id:str,strategy_key:str,
                          db_path="pricegauger.db") -> bool:
    """Fail closed on unreadable latch; reduction orders exempt upstream."""
    try:
        return load_trade_filter_v1(instance_id=instance_id,strategy_key=strategy_key,
                                    db_path=db_path).mode=="GO"
    except Exception:
        return False


__all__=["V3TradeFilterV1","ensure_trade_filter_schema_v1",
         "load_trade_filter_v1","set_trade_filter_v1","allow_new_exposure_v1"]
