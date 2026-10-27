"""Read-only per-account and fleet V3 worker observer."""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
from database import connect
from autotrader_v3_instance_registry_v1 import load_v3_instances_v1
from autotrader_v3_live_authority_v1 import live_authority_armed_v3
from autotrader_engine_account_ownership_v1 import load_account_owner_v1,ENGINE_V3
from autotrader_v3_config_v1 import load_autotrader_config_v3


def _clock(value):
    t=value if isinstance(value,datetime) else datetime.fromisoformat(str(value).replace("Z","+00:00"))
    return t.replace(tzinfo=timezone.utc) if t.tzinfo is None else t.astimezone(timezone.utc)


def ensure_monitor_schema(db_path="pricegauger.db"):
    with connect(db_path) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS pg_v3_fleet_monitor(
        instance_id TEXT NOT NULL, observed_minute TEXT NOT NULL,
        account_id TEXT NOT NULL,strategy_key TEXT NOT NULL,
        severity TEXT NOT NULL,status TEXT NOT NULL,
        signal TEXT NOT NULL,fill_count INTEGER NOT NULL,
        PRIMARY KEY(instance_id,observed_minute))""")


def assess(*, now, status, updated_at, pending, pending_at, fills):
    t=_clock(now)
    flags=[]
    if updated_at is None:
        flags.append("NO_HEARTBEAT")
    elif (t-_clock(updated_at)).total_seconds()>180:
        flags.append("STALE_HEARTBEAT")
    elif status in ("BLOCKED","DEGRADED","FAILED","UNKNOWN"):
        flags.append("RUNTIME_"+status)
    if pending:
        flags.append("UNRESOLVED_ORDER" if pending_at is None or
            (t-_clock(pending_at)).total_seconds()>120 else "ORDER_PENDING")
    if fills>=6:
        flags.append("HIGH_TURNOVER_REVIEW_SPREAD")
    severe=any(x in flags for x in
        ("STALE_HEARTBEAT","UNRESOLVED_ORDER","RUNTIME_FAILED"))
    return ("CRITICAL" if severe else "WARNING" if flags else "OK",
            ",".join(flags) if flags else "healthy")


def run_monitor_once(*,db_path="pricegauger.db",now=None):
    clock=_clock(now or datetime.now(timezone.utc))
    stamp=clock.replace(second=0,microsecond=0).isoformat()
    ensure_monitor_schema(db_path)
    rows=[]
    for inst in load_v3_instances_v1(db_path=db_path):
        if not live_authority_armed_v3(inst.instance_id,db_path=db_path):
            continue
        owner=load_account_owner_v1(inst.account_id,db_path=db_path)
        if owner is None or owner.engine_id!=ENGINE_V3 or owner.owner_key!=inst.instance_id:
            continue
        cfg=load_autotrader_config_v3(inst.instance_id,db_path=db_path)
        with connect(db_path) as db:
            try:
                runtime=db.execute("SELECT status,updated_at FROM autotrader_v3_live_runtime_state WHERE trader_id=?",
                    (inst.instance_id,)).fetchone()
            except Exception:runtime=None
            try:
                pending=db.execute("""SELECT state,updated_at FROM autotrader_v3_order_guard
                  WHERE trader_id=? AND account_id=? AND uic=? AND asset_type=?
                  AND state IN ('RESERVED','SUBMITTING','SUBMITTED','UNKNOWN')
                  ORDER BY updated_at DESC LIMIT 1""",
                  (inst.instance_id,inst.account_id,inst.uic,inst.asset_type)).fetchone()
            except Exception:
                pending={"state":"LEDGER_MISSING","updated_at":None}
            try:
                result=db.execute("""SELECT COUNT(*) AS n FROM autotrader_v3_execution_events
                   WHERE instance_id=? AND account_id=? AND uic=? AND asset_type=?
                   AND executed_at>=?""",
                   (inst.instance_id,inst.account_id,inst.uic,inst.asset_type,
                    (clock-timedelta(minutes=15)).isoformat())).fetchone()
                fills=int(result["n"] or 0)
            except Exception:fills=0
        status=str(runtime["status"]) if runtime else "UNKNOWN"
        updated=runtime["updated_at"] if runtime else None
        p_state=str(pending["state"]) if pending else None
        p_at=pending["updated_at"] if pending else None
        severity,signal=assess(now=clock,status=status,updated_at=updated,
             pending=p_state,pending_at=p_at,fills=fills)
        with connect(db_path) as db:
            db.execute("""INSERT INTO pg_v3_fleet_monitor(
               instance_id,observed_minute,account_id,strategy_key,
               severity,status,signal,fill_count)
               VALUES(?,?,?,?,?,?,?,?)
               ON CONFLICT(instance_id,observed_minute) DO UPDATE SET
               severity=excluded.severity,status=excluded.status,
               signal=excluded.signal,fill_count=excluded.fill_count""",
               (inst.instance_id,stamp,inst.account_id,cfg.strategy_key,
                severity,status,signal,fills))
        rows.append(dict(instance_id=inst.instance_id,account_id=inst.account_id,
            strategy_key=cfg.strategy_key,severity=severity,status=status,
            signal=signal,fill_count=fills,observed_minute=stamp))
    return tuple(rows)


def load_monitor_rows(*,db_path="pricegauger.db",limit=300):
    ensure_monitor_schema(db_path)
    with connect(db_path) as db:
        rows=db.execute("""SELECT * FROM pg_v3_fleet_monitor
          ORDER BY observed_minute DESC,instance_id LIMIT ?""",
          (max(1,min(int(limit),1000)),)).fetchall()
    return tuple(dict(r) for r in rows)
