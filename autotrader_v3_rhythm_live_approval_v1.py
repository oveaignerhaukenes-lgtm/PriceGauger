"""Explicit per-account LIVE pilot approval for rhythmic V3 strategies.

Independent of strategy catalog readiness and generic V3 LIVE arming. A
formerly blocked strategy on an already armed account must stay blocked
when this code is merged. No Saxo API calls or order submission here.
"""
from __future__ import annotations
from datetime import datetime, timezone
from database import connect

RHYTHM_CATALOG_KEYS_V3 = frozenset(("macd-stoch-rhythm-build", "rhythm-trend-1"))
RHYTHM_RUNTIME_KEYS_V3 = frozenset((
    "macd-stoch-rhythm-build-v1", "rhythm-trend-1-v1",
))
RUNTIME_TO_CATALOG_V3 = dict(zip(
    ("macd-stoch-rhythm-build-v1", "rhythm-trend-1-v1"),
    ("macd-stoch-rhythm-build", "rhythm-trend-1"),
))


def ensure_rhythm_live_approval_schema_v3(db_path="pricegauger.db"):
    with connect(db_path) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS autotrader_v3_rhythm_live_approval(
          trader_id TEXT PRIMARY KEY, strategy_key TEXT NOT NULL,
          account_id TEXT NOT NULL, uic INTEGER NOT NULL,
          asset_type TEXT NOT NULL, approved INTEGER NOT NULL,
          updated_at TEXT NOT NULL)""")


def _catalog_key(strategy_key):
    key=str(strategy_key)
    key=RUNTIME_TO_CATALOG_V3.get(key,key)
    if key not in RHYTHM_CATALOG_KEYS_V3:
        raise ValueError("not a supported rhythmic strategy")
    return key


def is_rhythm_live_approved_v3(
    trader_id, strategy_key, *, account_id, uic, asset_type, db_path="pricegauger.db",
) -> bool:
    """Fail-closed unless the exact strategy AND broker boundary was approved."""
    key=_catalog_key(strategy_key)
    ensure_rhythm_live_approval_schema_v3(db_path)
    with connect(db_path) as db:
        row=db.execute("""SELECT approved,strategy_key,account_id,uic,asset_type
            FROM autotrader_v3_rhythm_live_approval WHERE trader_id=?""",
            (str(trader_id),)).fetchone()
    if row is None:
        return False
    return (
        int(row["approved"]) == 1
        and str(row["strategy_key"]) == key
        and str(row["account_id"]) == str(account_id)
        and int(row["uic"]) == int(uic)
        and str(row["asset_type"]) == str(asset_type)
    )


def set_rhythm_live_approval_v3(
    trader_id, strategy_key, *, account_id, uic, asset_type,
    approved: bool, db_path="pricegauger.db",
) -> None:
    """Explicit UI-authorized update; no V3 armed status or order is changed."""
    key=_catalog_key(strategy_key)
    ensure_rhythm_live_approval_schema_v3(db_path)
    stamp=datetime.now(timezone.utc).isoformat()
    with connect(db_path) as db:
        db.execute("""INSERT INTO autotrader_v3_rhythm_live_approval(
            trader_id,strategy_key,account_id,uic,asset_type,approved,updated_at)
            VALUES(?,?,?,?,?,?,?)
            ON CONFLICT(trader_id) DO UPDATE SET
              strategy_key=excluded.strategy_key,
              account_id=excluded.account_id,uic=excluded.uic,
              asset_type=excluded.asset_type,approved=excluded.approved,
              updated_at=excluded.updated_at""",
            (str(trader_id),key,str(account_id),int(uic),str(asset_type),
             int(bool(approved)),stamp))


__all__=["RHYTHM_CATALOG_KEYS_V3","RHYTHM_RUNTIME_KEYS_V3",
          "is_rhythm_live_approved_v3","set_rhythm_live_approval_v3"]
