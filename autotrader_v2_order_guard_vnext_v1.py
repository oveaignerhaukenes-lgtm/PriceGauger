from __future__ import annotations

"""Durable single-flight order state for V2 execution vNext."""

from typing import Any

from database import connect

ACTIVE_STATES = ("RESERVED", "SUBMITTING", "SUBMITTED", "UNKNOWN")


def ensure_v2_order_guard_vnext_v1(*, db_path: str = "pricegauger.db") -> None:
    with connect(db_path) as db:
        db.execute("""
        CREATE TABLE IF NOT EXISTS autotrader_v2_vnext_orders(
          request_key TEXT PRIMARY KEY,
          trader_id TEXT NOT NULL,
          account_id TEXT NOT NULL,
          uic INTEGER NOT NULL,
          asset_type TEXT NOT NULL,
          actual_inventory REAL NOT NULL,
          expected_inventory REAL NOT NULL,
          submitted_amount REAL NOT NULL,
          submitted_side TEXT NOT NULL,
          state TEXT NOT NULL,
          broker_order_id TEXT,
          detail TEXT,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """)


def pending_order_v2_vnext_v1(*, account_id: str, uic: int, asset_type: str, db_path: str = "pricegauger.db") -> dict[str, Any] | None:
    ensure_v2_order_guard_vnext_v1(db_path=db_path)
    with connect(db_path) as db:
        row = db.execute(
            """SELECT * FROM autotrader_v2_vnext_orders
               WHERE account_id=? AND uic=? AND asset_type=?
                 AND state IN ('RESERVED','SUBMITTING','SUBMITTED','UNKNOWN')
               ORDER BY created_at ASC LIMIT 1""",
            (str(account_id), int(uic), str(asset_type)),
        ).fetchone()
    return None if row is None else dict(row)


def reserve_order_v2_vnext_v1(*, request_key: str, trader_id: str, account_id: str, uic: int, asset_type: str, actual_inventory: float, expected_inventory: float, submitted_amount: float, submitted_side: str, db_path: str = "pricegauger.db") -> bool:
    ensure_v2_order_guard_vnext_v1(db_path=db_path)
    if pending_order_v2_vnext_v1(account_id=account_id, uic=uic, asset_type=asset_type, db_path=db_path) is not None:
        return False
    with connect(db_path) as db:
        existing = db.execute("SELECT state FROM autotrader_v2_vnext_orders WHERE request_key=?", (str(request_key),)).fetchone()
        if existing is not None:
            return False
        db.execute(
            """INSERT INTO autotrader_v2_vnext_orders(
               request_key,trader_id,account_id,uic,asset_type,actual_inventory,
               expected_inventory,submitted_amount,submitted_side,state)
               VALUES(?,?,?,?,?,?,?,?,?,'RESERVED')""",
            (str(request_key), str(trader_id), str(account_id), int(uic), str(asset_type), float(actual_inventory), float(expected_inventory), float(submitted_amount), str(submitted_side)),
        )
    return True


def mark_order_v2_vnext_v1(*, request_key: str, state: str, broker_order_id: str | None = None, detail: str | None = None, db_path: str = "pricegauger.db") -> None:
    ensure_v2_order_guard_vnext_v1(db_path=db_path)
    with connect(db_path) as db:
        db.execute(
            """UPDATE autotrader_v2_vnext_orders
               SET state=?, broker_order_id=COALESCE(?,broker_order_id), detail=?, updated_at=CURRENT_TIMESTAMP
               WHERE request_key=?""",
            (str(state), broker_order_id, detail, str(request_key)),
        )
