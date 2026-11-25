"""Verified final-fill evidence for Mirror Lab, isolated from LIVE execution.

Existing inspection reads can persist verified results without new requests.
Optional collection uses at most one exact account audit per ten minutes
across this worker, only for recent missing fills. Disabled by default.
"""
from datetime import datetime,timedelta,timezone
import json
from database import connect,run_postgres_schema_once_v1
from live_mirror_registry_v1 import _stamp
from live_mirror_validation_v1 import VerifiedFill


def ensure_audit_schema(db_path):
    def initialize():
        with connect(db_path) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS pg_live_mirror_verified_fill_v1(
                account_id TEXT NOT NULL, uic INTEGER NOT NULL, asset_type TEXT NOT NULL,
                broker_order_id TEXT NOT NULL, price DOUBLE PRECISION NOT NULL,
                filled_at TEXT NOT NULL, observed_at TEXT NOT NULL,
                PRIMARY KEY(account_id,uic,asset_type,broker_order_id))""")
            db.execute("""CREATE TABLE IF NOT EXISTS pg_live_mirror_audit_throttle_v1(
                slot TEXT PRIMARY KEY, attempted_at TEXT NOT NULL)""")
    run_postgres_schema_once_v1("pg_live_mirror_verified_fill_v1",initialize)


def persist_verified_fills(prices, *, account_id,uic,asset_type,db_path="pricegauger.db",now=None):
    from math import isfinite
    now=now or datetime.now(timezone.utc)
    ensure_audit_schema(db_path)
    saved=0
    with connect(db_path) as db:
        for order_id,v in prices.items():
            if v.get("price_source")!="SAXO_FINAL_FILL" or not order_id:
                continue
            try:
                at=_stamp(v["filled_at"])
                price=float(v["execution_price"])
                if not at or at>now or not isfinite(price) or price<=0:
                    continue
            except (TypeError,ValueError,KeyError):
                continue
            result=db.execute("""INSERT INTO pg_live_mirror_verified_fill_v1
                (account_id,uic,asset_type,broker_order_id,price,filled_at,observed_at)
                VALUES(?,?,?,?,?,?,?) ON CONFLICT DO NOTHING""",
                (str(account_id),int(uic),str(asset_type),str(order_id),price,at.isoformat(),now.isoformat()))
            saved+=max(0,result.rowcount)
    return saved


def collect_one_audit(*,db_path="pricegauger.db",now=None,fetch=None,active_only=False):
    """Explicit opt-in worker action, only an exact read-only Saxo audit.

    Claim the durable ten-minute slot before any network call. Failed calls
    are not retried inside that slot. Never request precheck or place orders.
    """
    now=now or datetime.now(timezone.utc)
    ensure_audit_schema(db_path)
    with connect(db_path) as db:
        scope = """ AND EXISTS (SELECT 1 FROM pg_live_mirror_registry_v1 m WHERE m.instance_id=e.instance_id AND m.active=TRUE)""" if active_only else ""
        candidates=db.execute("""SELECT e.account_id,e.uic,e.asset_type,
            e.broker_order_id,e.side,e.amount,e.executed_at
            FROM autotrader_v3_execution_events e
            JOIN pg_live_mirror_trace_v1 t ON t.event_key=('submission:' || e.request_key)
            LEFT JOIN pg_live_mirror_verified_fill_v1 f
              ON f.account_id=e.account_id AND f.uic=e.uic AND f.asset_type=e.asset_type
              AND f.broker_order_id=e.broker_order_id
            WHERE f.broker_order_id IS NULL AND e.executed_at>=?
            """+scope+""" ORDER BY e.executed_at ASC LIMIT 120""",(now-timedelta(hours=24),)).fetchall()
        if not candidates:
            return "NO_MISSING_FILLS"
        boundaries=list(dict.fromkeys((str(r["account_id"]),int(r["uic"]),str(r["asset_type"])) for r in candidates))
        chosen=boundaries[int(now.timestamp()//600)%len(boundaries)]
        first=next(r for r in candidates if (str(r["account_id"]),int(r["uic"]),str(r["asset_type"]))==chosen)
        boundary=(str(first["account_id"]),int(first["uic"]),str(first["asset_type"]))
        events=[dict(r) for r in candidates if (str(r["account_id"]),int(r["uic"]),str(r["asset_type"]))==boundary][:30]
        # Global time slot, independent of service restart.
        slot=now.replace(minute=now.minute//10*10,second=0,microsecond=0).isoformat()
        result=db.execute("""INSERT INTO pg_live_mirror_audit_throttle_v1(slot,attempted_at)
                          VALUES(?,?) ON CONFLICT DO NOTHING""",(slot,now.isoformat()))
        if result.rowcount!=1:
            return "THROTTLED"
    if fetch is None:
        from autotrader_v3_instance_fill_prices_v1 import fetch_exact_final_fills_v1
        fetch=fetch_exact_final_fills_v1
    prices=fetch(events,account_id=boundary[0],uic=boundary[1],asset_type=boundary[2],now=now)
    count=persist_verified_fills(prices,account_id=boundary[0],uic=boundary[1],
                                 asset_type=boundary[2],db_path=db_path,now=now)
    return "VERIFIED:"+str(count)


def calibration_samples(*,instance_id,db_path="pricegauger.db",limit=500):
    """Exact decision -> submission -> reconciled order -> verified final fill.

    Missing or ambiguous evidence is reported; never use reconciliation
    timestamp as fill time. BBO is the last quote already received at fill.
    """
    ensure_audit_schema(db_path)
    with connect(db_path) as db:
        rows=db.execute("""SELECT e.instance_id,e.uic,e.asset_type,e.side,e.amount,
            s.decision_key,d.observed_at AS decided_at,f.filled_at,f.price
            FROM autotrader_v3_execution_events e
            JOIN pg_live_mirror_trace_v1 s ON s.event_key=('submission:' || e.request_key)
            JOIN pg_live_mirror_trace_v1 d ON d.instance_id=e.instance_id
                AND d.decision_key=s.decision_key AND d.event_type='DECISION'
            JOIN pg_live_mirror_verified_fill_v1 f ON f.account_id=e.account_id
                AND f.uic=e.uic AND f.asset_type=e.asset_type AND f.broker_order_id=e.broker_order_id
            WHERE e.instance_id=? ORDER BY f.filled_at DESC LIMIT ?""",
            (str(instance_id),max(1,min(int(limit),5000)))).fetchall()
        samples=[];missing=0;seen=set()
        for r in rows:
            identity=str(r["decision_key"])
            if identity in seen:
                missing+=1
                # Multi-submit intent needs exact tranche-level matching.
                samples=[s for s in samples if s.decision_id!=identity]
                continue
            seen.add(identity)
            q=db.execute("""SELECT bid,ask,received_at,quote_at FROM lsim_hyper_quotes_1s
                WHERE provider_uic=? AND asset_type=? AND received_at<=? AND received_at>=?
                ORDER BY received_at DESC LIMIT 1""",
                (int(r["uic"]),str(r["asset_type"]),str(r["filled_at"]),
                 (_stamp(r["filled_at"])-timedelta(seconds=2)).isoformat())).fetchone()
            if q is None:
                missing+=1
                continue
            try:
                if not 0<=(_stamp(q["received_at"])-_stamp(q["quote_at"])).total_seconds()<=5:
                    raise ValueError("stale quote")
                samples.append(VerifiedFill(identity,str(instance_id),
                    str(r["uic"])+":"+str(r["asset_type"]),str(r["side"]).upper(),
                    float(r["amount"]),_stamp(r["decided_at"]),_stamp(r["filled_at"]),
                    float(r["price"]),float(q["bid"]),float(q["ask"]),
                    _stamp(q["received_at"]),"SAXO_FINAL_FILL"))
            except (TypeError,ValueError):
                missing+=1
        return tuple(reversed(samples)),missing
