from __future__ import annotations

from dataclasses import dataclass

from database import connect


@dataclass(frozen=True, slots=True)
class V3CapacityHold:
    trader_id: str
    direction: str
    cap_nok: float
    inventory_amount: float
    context_key: str


def ensure_capacity_hold_schema_v3(db_path: str = "pricegauger.db") -> None:
    with connect(db_path) as db:
        db.execute(
            """CREATE TABLE IF NOT EXISTS autotrader_v3_capacity_hold (
              trader_id TEXT PRIMARY KEY,
              direction TEXT NOT NULL,
              cap_nok DOUBLE PRECISION NOT NULL,
              inventory_amount DOUBLE PRECISION NOT NULL,
              context_key TEXT NOT NULL,
              updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )"""
        )


def load_capacity_hold_v3(*, trader_id: str, db_path: str = "pricegauger.db") -> V3CapacityHold | None:
    ensure_capacity_hold_schema_v3(db_path)
    with connect(db_path) as db:
        row = db.execute(
            """SELECT trader_id,direction,cap_nok,inventory_amount,context_key
               FROM autotrader_v3_capacity_hold WHERE trader_id=?""",
            (str(trader_id),),
        ).fetchone()
    if row is None:
        return None
    get = lambda key, index: row[key] if isinstance(row, dict) else row[index]
    return V3CapacityHold(
        trader_id=str(get("trader_id", 0)),
        direction=str(get("direction", 1)).upper(),
        cap_nok=float(get("cap_nok", 2)),
        inventory_amount=float(get("inventory_amount", 3)),
        context_key=str(get("context_key", 4)),
    )


def save_capacity_hold_v3(*, trader_id: str, direction: str, cap_nok: float,
                          inventory_amount: float, context_key: str,
                          db_path: str = "pricegauger.db") -> None:
    normalized=str(direction or "").upper()
    if normalized not in {"LONG", "SHORT"}:
        raise ValueError("capacity hold direction must be LONG or SHORT")
    if float(cap_nok) <= 0:
        raise ValueError("capacity hold cap must be positive")
    ensure_capacity_hold_schema_v3(db_path)
    with connect(db_path) as db:
        db.execute(
            """INSERT INTO autotrader_v3_capacity_hold(
                 trader_id,direction,cap_nok,inventory_amount,context_key,updated_at)
               VALUES(?,?,?,?,?,CURRENT_TIMESTAMP)
               ON CONFLICT(trader_id) DO UPDATE SET
                 direction=excluded.direction,
                 cap_nok=excluded.cap_nok,
                 inventory_amount=excluded.inventory_amount,
                 context_key=excluded.context_key,
                 updated_at=CURRENT_TIMESTAMP""",
            (str(trader_id), normalized, float(cap_nok), float(inventory_amount), str(context_key)),
        )


def clear_capacity_hold_v3(*, trader_id: str, db_path: str = "pricegauger.db") -> bool:
    ensure_capacity_hold_schema_v3(db_path)
    with connect(db_path) as db:
        cursor=db.execute(
            "DELETE FROM autotrader_v3_capacity_hold WHERE trader_id=?",
            (str(trader_id),),
        )
    return cursor.rowcount > 0


def capacity_hold_blocks_v3(*, hold: V3CapacityHold, desired_direction: str,
                            actual_amount: float, cap_nok: float,
                            context_key: str) -> bool:
    """True only while the same saturated expansion context is still intact."""
    direction=str(desired_direction or "").upper()
    if direction not in {"LONG", "SHORT"}:
        return False
    if str(context_key) != hold.context_key:
        return False
    if abs(float(cap_nok)-hold.cap_nok) > 1e-9:
        return False
    if direction != hold.direction:
        return False

    actual=float(actual_amount)
    held_abs=abs(float(hold.inventory_amount))
    actual_abs=abs(actual)
    # Any reduction from the inventory observed at saturation frees the hold.
    if actual_abs + 1e-9 < held_abs:
        return False
    # A broker move to the opposite side also frees it.
    if actual_abs > 1e-12:
        actual_direction="LONG" if actual > 0 else "SHORT"
        if actual_direction != hold.direction:
            return False
    return True


__all__=[
    "V3CapacityHold",
    "capacity_hold_blocks_v3",
    "clear_capacity_hold_v3",
    "ensure_capacity_hold_schema_v3",
    "load_capacity_hold_v3",
    "save_capacity_hold_v3",
]
