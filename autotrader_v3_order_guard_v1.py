"""Durable, fail-closed V3 order-intent reservation per Saxo account/product."""
from database import connect, using_postgres

UNRESOLVED = ("RESERVED", "SUBMITTING", "SUBMITTED", "UNKNOWN")

def ensure_schema(db_path="pricegauger.db"):
    with connect(db_path) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS autotrader_v3_order_guard (
            request_key TEXT PRIMARY KEY, trader_id TEXT NOT NULL,
            account_id TEXT NOT NULL, uic INTEGER NOT NULL, asset_type TEXT NOT NULL,
            state TEXT NOT NULL, broker_order_id TEXT, detail TEXT,
            expected_inventory REAL, submitted_amount REAL, submitted_side TEXT,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
        if using_postgres():
            for name,kind in (("expected_inventory","DOUBLE PRECISION"),
                              ("submitted_amount","DOUBLE PRECISION"),
                              ("submitted_side","TEXT")):
                db.execute(f"ALTER TABLE autotrader_v3_order_guard ADD COLUMN IF NOT EXISTS {name} {kind}")
        else:
            existing={row[1] for row in db.execute("PRAGMA table_info(autotrader_v3_order_guard)").fetchall()}
            for name,kind in (("expected_inventory","REAL"),("submitted_amount","REAL"),
                              ("submitted_side","TEXT")):
                if name not in existing:
                    db.execute(f"ALTER TABLE autotrader_v3_order_guard ADD COLUMN {name} {kind}")
        db.execute("""CREATE UNIQUE INDEX IF NOT EXISTS uq_v3_unresolved_boundary
            ON autotrader_v3_order_guard(account_id,uic,asset_type)
            WHERE state IN ('RESERVED','SUBMITTING','SUBMITTED','UNKNOWN')""")

def reserve(*, request_key, trader_id, account_id, uic, asset_type,
            expected_inventory=None, submitted_amount=None, submitted_side=None,
            db_path="pricegauger.db"):
    ensure_schema(db_path)
    with connect(db_path) as db:
        db.execute("""INSERT INTO autotrader_v3_order_guard
            (request_key,trader_id,account_id,uic,asset_type,state,
             expected_inventory,submitted_amount,submitted_side)
            VALUES(?,?,?,?,?,'RESERVED',?,?,?)""",
            (request_key,trader_id,account_id,int(uic),asset_type,
             expected_inventory,submitted_amount,submitted_side))

def mark(*, request_key, state, broker_order_id=None, detail=None, db_path="pricegauger.db"):
    if state not in (*UNRESOLVED, "RECONCILED", "REJECTED"):
        raise ValueError("invalid V3 order state")
    ensure_schema(db_path)
    event=None
    with connect(db_path) as db:
        cursor=db.execute("""UPDATE autotrader_v3_order_guard
            SET state=?, broker_order_id=COALESCE(?,broker_order_id),
            detail=?,updated_at=CURRENT_TIMESTAMP WHERE request_key=?""",
            (state,broker_order_id,detail,request_key))
        if cursor.rowcount != 1:
            raise LookupError("missing V3 order reservation")
        # Only exact post-order inventory confirmation is an execution event.
        # Inventory-adoption reconciliation deliberately does not create one.
        if state == "RECONCILED" and detail == "Exact Saxo inventory reached expected post-order position":
            row=db.execute("""SELECT g.trader_id,g.account_id,g.uic,g.asset_type,
                g.expected_inventory,g.submitted_amount,g.submitted_side,g.broker_order_id,i.market_name
                FROM autotrader_v3_order_guard g
                JOIN autotrader_v3_engine_instances i
                  ON i.instance_id=g.trader_id AND i.account_id=g.account_id
                 AND i.uic=g.uic AND i.asset_type=g.asset_type
                WHERE g.request_key=?""",(request_key,)).fetchone()
            if row is not None:
                if isinstance(row,dict): event=dict(row)
                else: event=dict(zip(("trader_id","account_id","uic","asset_type","expected_inventory","submitted_amount","submitted_side","broker_order_id","market_name"),row))
    if event is not None:
        from autotrader_v3_execution_events_v1 import record_reconciled_execution_v1
        record_reconciled_execution_v1(request_key=request_key,instance_id=event["trader_id"],
            account_id=event["account_id"],uic=event["uic"],asset_type=event["asset_type"],
            market_name=event["market_name"],submitted_side=event["submitted_side"],
            submitted_amount=event["submitted_amount"],expected_inventory=event["expected_inventory"],
            broker_order_id=event["broker_order_id"],db_path=db_path)

def unresolved(*, account_id, uic, asset_type, db_path="pricegauger.db"):
    ensure_schema(db_path)
    with connect(db_path) as db:
        return db.execute("""SELECT request_key,state FROM autotrader_v3_order_guard
            WHERE account_id=? AND uic=? AND asset_type=?
            AND state IN ('RESERVED','SUBMITTING','SUBMITTED','UNKNOWN') LIMIT 1""",
            (account_id,int(uic),asset_type)).fetchone()


def pending_order(*, account_id, uic, asset_type, db_path="pricegauger.db"):
    """Fetch durable order evidence; old reservations without expected inventory stay locked."""
    ensure_schema(db_path)
    with connect(db_path) as db:
        row=db.execute("""SELECT request_key,state,broker_order_id,
            expected_inventory,submitted_amount,submitted_side,updated_at
            FROM autotrader_v3_order_guard
            WHERE account_id=? AND uic=? AND asset_type=?
            AND state IN ('RESERVED','SUBMITTING','SUBMITTED','UNKNOWN') LIMIT 1""",
            (account_id,int(uic),asset_type)).fetchone()
    if row is None:
        return None
    if isinstance(row,dict):
        return dict(row)
    return dict(zip(("request_key","state","broker_order_id","expected_inventory",
                     "submitted_amount","submitted_side","updated_at"),row))
