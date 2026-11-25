"""Prospective LIVE Mirror Lab discovery and reference snapshots.

Only reads existing LIVE tables. Writes exclusively pg_live_mirror_* tables.
This phase registers twins and evidence; does not pretend a reference
heartbeat is a fill, a non-flat position has a known basis, or a model is
calibrated. No Saxo or AI calls, no LIVE/SIM authority mutations.
"""
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import math
import re
from database import connect, run_postgres_schema_once_v1


def _json(value):
    return json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))


def _stamp(value):
    if value is None:
        return None
    try:
        t = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return t.replace(tzinfo=timezone.utc) if t.tzinfo is None else t.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def _fresh(value, now, max_age):
    stamp = _stamp(value)
    return stamp is not None and 0 <= (now-stamp).total_seconds() <= max_age


def _rows(db_path, sql, args=()):
    with connect(db_path) as db:
        return tuple(dict(row) for row in db.execute(sql, args).fetchall())


def _optional(db_path, sql, args=()):
    try:
        return _rows(db_path, sql, args)
    except Exception:
        # An unavailable source is not an empty/disabled configuration.
        return None


def _first(rows):
    return rows[0] if rows else None


def ensure_mirror_schema(db_path):
    def initialize():
        with connect(db_path) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS pg_live_mirror_registry_v1 (
                mirror_id TEXT PRIMARY KEY, instance_id TEXT NOT NULL,
                account_name TEXT NOT NULL, market_name TEXT NOT NULL,
                config_json TEXT NOT NULL, reference_json TEXT NOT NULL,
                status TEXT NOT NULL, active BOOLEAN NOT NULL,
                created_at TEXT NOT NULL, observed_at TEXT NOT NULL)""")
            db.execute("""CREATE INDEX IF NOT EXISTS pg_live_mirror_instance_v1
                ON pg_live_mirror_registry_v1(instance_id,active)""")
    run_postgres_schema_once_v1("pg_live_mirror_registry_v1", initialize)


def _without_clock(row):
    if row is None:
        return None
    return {k:v for k,v in row.items() if k not in ("updated_at",)}


def collect_reference(instance, *, now, db_path):
    identity = str(instance["instance_id"])
    account = str(instance["account_id"])
    uic, asset = int(instance["uic"]), str(instance["asset_type"])
    config = _optional(db_path, """SELECT strategy_key,timeframe,control_mode,
        modifiers_json,regime_timeframe,exit_timeframe FROM autotrader_v3_config
        WHERE trader_id=?""", (identity,))
    policy = _optional(db_path, """SELECT budget_nok,exposure_pct
        FROM autotrader_v3_execution_policy WHERE trader_id=?""", (identity,))
    regime = _optional(db_path, """SELECT strategy_key,mode,allow_bull,allow_bear,
        allow_sideways,trend_only,block_unknown FROM pg_v3_regime_entry_policy_v1
        WHERE instance_id=?""", (identity,))
    stop = _optional(db_path, """SELECT strategy_key,mode,source
        FROM pg_v3_trade_filter_control_v1 WHERE instance_id=?""", (identity,))
    modifiers = _optional(db_path, """SELECT modifier_key,settings_json
        FROM autotrader_v3_modifier_settings WHERE trader_id=? ORDER BY modifier_key""", (identity,))
    heartbeat = _first(_optional(db_path, """SELECT status,detail,updated_at
        FROM autotrader_v3_live_runtime_state WHERE trader_id=?""", (identity,)))
    truth = _first(_optional(db_path, """SELECT account_name,currency,total_value,cash_balance,
        margin_used,margin_utilization_pct,calculation_reliability,observed_at
        FROM pg_saxo_account_truth_v1 WHERE account_id=? AND observed_at<=?
        ORDER BY observed_at DESC LIMIT 1""", (account,now.isoformat())))
    quote = _first(_optional(db_path, """SELECT quote_at,received_at,bid,ask
        FROM lsim_hyper_quotes_1s WHERE provider_uic=? AND asset_type=?
        AND received_at<=? AND quote_at>=? ORDER BY quote_at DESC LIMIT 1""",
        (uic,asset,now.isoformat(),(now-timedelta(seconds=30)).isoformat())))
    pending = _optional(db_path, """SELECT state FROM autotrader_v3_order_guard
        WHERE account_id=? AND uic=? AND asset_type=?
        AND state IN ('RESERVED','SUBMITTING','SUBMITTED','UNKNOWN')""", (account,uic,asset))
    settings = {"boundary": {"account_id":account,"uic":uic,"asset_type":asset,
                            "instrument_id":int(instance["instrument_id"])},
                "strategy":_first(config),"capital":_first(policy),
                "regime":_first(regime),"stop":_first(stop),
                "modifier_settings":modifiers,
                "missing_sources":[k for k,v in (("config",config),("capital",policy),
                    ("regime",regime),("stop",stop),("modifiers",modifiers)) if v is None]}
    # Actual inventory is a heartbeat observation, not a fresh broker read.
    m = re.search(r"(?<!\w)actual=([-+]?\d+(?:\.\d+)?)", str((heartbeat or {}).get("detail","")))
    actual = float(m.group(1)) if m else None
    if actual is not None and not math.isfinite(actual):
        actual = None
    reference = {"heartbeat":heartbeat,"account":truth,"quote":quote,
                 "actual_observed":actual,"pending":pending}
    if settings["missing_sources"] or not settings["strategy"] or not settings["capital"]:
        status = "WAIT_CONFIG"
    elif pending is None or pending or not heartbeat or not _fresh(heartbeat["updated_at"],now,30):
        status = "WAIT_ORDER_TRUTH"
    elif heartbeat["status"] not in ("READY","MANAGING","RECONCILED") or actual is None:
        status = "WAIT_ORDER_TRUTH"
    elif abs(actual)>1e-9:
        status = "WAIT_FLAT_BASELINE"
    elif (not truth or str(truth["calculation_reliability"]).lower()!="ok"
          or not _fresh(truth["observed_at"],now,360)
          or str(truth["currency"]).upper()!="NOK"
          or not math.isfinite(float(truth["total_value"])) or float(truth["total_value"])<=0):
        status = "WAIT_ACCOUNT_BASELINE"
    elif not quote or not _fresh(quote["received_at"],now,10) or not _fresh(quote["quote_at"],now,10):
        status = "WAIT_BBO"
    else:
        status = "WAIT_CALIBRATION"
    return settings, reference, status


def refresh_mirror_registry(*, db_path="pricegauger.db", now=None):
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        raise ValueError("timezone-aware clock required")
    moment=moment.astimezone(timezone.utc)
    # Only armed enabled instances. No bootstrap or authority/schema writer.
    active = _rows(db_path, """SELECT i.instance_id,i.account_id,i.uic,i.asset_type,
        i.instrument_id,i.market_name FROM autotrader_v3_engine_instances i
        JOIN autotrader_v3_live_authority a ON a.trader_id=i.instance_id
        WHERE i.enabled=TRUE AND a.armed=TRUE ORDER BY i.instance_id""")
    prepared=[]
    for instance in active:
        settings,reference,status=collect_reference(instance,now=moment,db_path=db_path)
        instance_id=str(instance["instance_id"])
        version=sha256(_json(settings).encode()).hexdigest()
        mirror_id="mirror:"+instance_id+":"+version
        name=str((reference.get("account") or {}).get("account_name") or instance_id[:8])
        prepared.append((mirror_id,instance_id,name,str(instance["market_name"]),
                         _json(settings),_json(reference),status,moment.isoformat(),moment.isoformat()))
    ensure_mirror_schema(db_path)
    with connect(db_path) as db:
        # The cohort is replaced atomically only after a successful source scan.
        # Historical config revisions remain available.
        db.execute("UPDATE pg_live_mirror_registry_v1 SET active=FALSE WHERE active=TRUE")
        for row in prepared:
            db.execute("""INSERT INTO pg_live_mirror_registry_v1
                (mirror_id,instance_id,account_name,market_name,config_json,reference_json,
                 status,active,created_at,observed_at) VALUES(?,?,?,?,?,?,?,TRUE,?,?)
                ON CONFLICT(mirror_id) DO UPDATE SET account_name=excluded.account_name,
                 reference_json=excluded.reference_json,status=excluded.status,
                 active=TRUE,observed_at=excluded.observed_at""",row)
    return len(prepared)


def mirror_snapshot(*, db_path="pricegauger.db"):
    """Read-only view; a missing table is not evidence of zero active mirrors."""
    return _optional(db_path, """SELECT mirror_id,instance_id,account_name,market_name,
        config_json,reference_json,status,created_at,observed_at
        FROM pg_live_mirror_registry_v1 WHERE active=TRUE ORDER BY account_name,instance_id""")
