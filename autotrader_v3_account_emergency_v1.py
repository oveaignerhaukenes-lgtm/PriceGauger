"""Account-wide V3 emergency quarantine and broker reconciliation.

Never clear a broker-ambiguous order just because it is old. The recovery
coordinator is serialized with each account's normal V3 lane; ordinary V3
mutations are disabled for the account while an incident is active.
Automatic broker writes require an explicit deployment opt-in.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import isfinite
from uuid import NAMESPACE_URL, uuid5
import logging
import os

from database import connect, run_postgres_schema_once_v1, using_postgres
from autotrader_v3_order_guard_v1 import (
    pending_order, reserve, claim_reserved_for_submission_v3, mark,
)
from saxo_provider import SaxoInstrument
from saxo_trading import SaxoOrderRequest

LOG = logging.getLogger("pricegauger.v3.emergency")
ACTIVE = frozenset({"PAUSED", "BROKER_DOWN", "AUTH_REQUIRED", "RESOLVING", "CANCELLING", "CLOSING", "VERIFYING"})
GRACE_SECONDS = 90  # never treat absence from one snapshot as a failed POST
FLAT_CONFIRM_SECONDS = 5


@dataclass(frozen=True, slots=True)
class AccountEmergencyV1:
    account_id: str
    state: str
    reason: str
    started_at: str
    updated_at: str
    flat_seen_at: str | None


def _now(now=None):
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        raise ValueError("emergency clock must be timezone aware")
    return value.astimezone(timezone.utc)


def _dt(raw):
    if isinstance(raw, datetime):
        value = raw
    else:
        value = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _init(db_path):
    with connect(db_path) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS pg_v3_account_emergency_v1(
            account_id TEXT PRIMARY KEY,
            state TEXT NOT NULL, reason TEXT NOT NULL,
            started_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            flat_seen_at TEXT
        )""")


def ensure_schema_v1(db_path="pricegauger.db"):
    if using_postgres():
        run_postgres_schema_once_v1("pg_v3_account_emergency_v1", lambda: _init(db_path))
    else:
        _init(db_path)


def load_emergency_v1(account_id, *, db_path="pricegauger.db"):
    ensure_schema_v1(db_path)
    with connect(db_path) as db:
        row = db.execute(
            "SELECT * FROM pg_v3_account_emergency_v1 WHERE account_id=?",
            (str(account_id),),
        ).fetchone()
    if row is None:
        return None
    values = dict(row)
    return AccountEmergencyV1(**values)


def emergency_active_v1(account_id, *, db_path="pricegauger.db"):
    incident = load_emergency_v1(account_id, db_path=db_path)
    return incident is not None and incident.state in ACTIVE

def active_emergency_accounts_v1(*, db_path="pricegauger.db"):
    """Emergency routes survive strategy OFF and restart (read-only)."""
    ensure_schema_v1(db_path)
    with connect(db_path) as db:
        rows = db.execute(
            "SELECT account_id FROM pg_v3_account_emergency_v1 WHERE state!='RESUMED'"
        ).fetchall()
    return tuple(str(r["account_id"] if isinstance(r,dict) else r[0]) for r in rows)


def _error_state(exc):
    code = getattr(exc, "status_code", None)
    if code in {401,403}:
        return "AUTH_REQUIRED"
    return "BROKER_DOWN"


def should_start_emergency_v1(pending, *, now=None):
    """Stale unknown broker mutation becomes an account incident, not a silent lock.

    UNKNOWN means the POST result was ambiguous. A confirmed broker fill is
    already reconciled upstream, so this is called only on unresolved WAIT.
    """
    if not isinstance(pending, dict):
        return False
    state = str(pending.get("state") or "").upper()
    if state not in {"UNKNOWN", "SUBMITTING", "SUBMITTED", "RESERVED"}:
        return False
    try:
        age = (_now(now) - _dt(pending["updated_at"])).total_seconds()
    except (ValueError, TypeError, KeyError):
        return True
    threshold = 15 if state == "UNKNOWN" else 90 if state != "RESERVED" else 120
    return age >= threshold


def activate_emergency_v1(account_id, reason, *, db_path="pricegauger.db", now=None):
    """Durable, idempotent account-wide STOP; never change LIVE authority."""
    account = str(account_id or "").strip()
    if not account:
        raise ValueError("account required")
    stamp = _now(now).isoformat()
    ensure_schema_v1(db_path)
    with connect(db_path) as db:
        db.execute(
            """INSERT INTO pg_v3_account_emergency_v1(
                account_id,state,reason,started_at,updated_at,flat_seen_at)
               VALUES(?,'PAUSED',?,?,?,NULL)
               ON CONFLICT(account_id) DO UPDATE SET
                 state=CASE WHEN state='RESUMED' THEN 'PAUSED' ELSE state END,
                 reason=CASE WHEN state='RESUMED' THEN excluded.reason ELSE reason END,
                 started_at=CASE WHEN state='RESUMED' THEN excluded.started_at ELSE started_at END,
                 updated_at=excluded.updated_at,
                 flat_seen_at=CASE WHEN state='RESUMED' THEN NULL ELSE flat_seen_at END""",
            (account, str(reason)[:160], stamp, stamp),
        )
    LOG.critical("V3 EMERGENCY account_suffix=%s reason=%s", account[-4:], str(reason)[:100])


def _set(account, state, reason, *, db_path, now, flat_seen_at=None):
    if state not in ACTIVE | {"RESUMED"}:
        raise ValueError("invalid emergency state")
    with connect(db_path) as db:
        db.execute(
            """UPDATE pg_v3_account_emergency_v1
               SET state=?,reason=?,updated_at=?,flat_seen_at=?
               WHERE account_id=? AND state!='RESUMED'""",
            (state, reason[:160], now.isoformat(), flat_seen_at, account),
        )
    LOG.warning("V3 emergency account_suffix=%s phase=%s reason=%s",
                account[-4:], state, reason[:100])


def _get_list(client, path, params):
    response = client._get(path, params=params)
    if (not isinstance(response, dict) or response.get("__next")
        or response.get("Next") or not isinstance(response.get("Data"), list)
        or len(response["Data"]) >= int(params.get("$top", 1000))):
        raise RuntimeError("INCOMPLETE_BROKER_RESPONSE_" + path.split("/")[-1])
    return response["Data"]


def _working_orders(broker, account_id, account_key):
    rows = _get_list(broker.client, "port/v1/orders/me", {"$top": 1000})
    found = []
    for item in rows:
        if not isinstance(item, dict):
            raise RuntimeError("INVALID_BROKER_ORDER")
        a = str(item.get("AccountId") or "")
        k = str(item.get("AccountKey") or "")
        if not (a or k):
            raise RuntimeError("UNSCOPED_WORKING_ORDER")
        if a == account_id or k == account_key:
            if a and a != account_id:
                raise RuntimeError("WRONG_ORDER_ACCOUNT")
            if k and k != account_key:
                raise RuntimeError("WRONG_ORDER_KEY")
            found.append(item)
    return found


def _positions(broker, account_id, account_key, client_key):
    params = {"$top": 1000, "AccountKey": account_key, "FieldGroups": "PositionBase,PositionView"}
    if client_key:
        params["ClientKey"] = client_key
    rows = _get_list(broker.client, "port/v1/positions", params)
    found = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("PositionBase"), dict):
            raise RuntimeError("INVALID_BROKER_POSITION")
        base = row["PositionBase"]
        owner = str(base.get("AccountId") or base.get("PositionsAccount") or "")
        if owner != account_id:
            raise RuntimeError("WRONG_POSITION_ACCOUNT")
        if str(base.get("Status") or "").lower() in {"closed"}:
            continue
        pid = str(row.get("PositionId") or "")
        side = str(base.get("OpeningDirection") or "").lower()
        amount = float(base.get("Amount") or 0)
        if (not pid or side not in {"buy", "sell"} or not isfinite(amount)
            or amount <= 0 or int(base.get("Uic") or 0) <= 0
            or not base.get("AssetType")):
            raise RuntimeError("INVALID_OPEN_POSITION")
        found.append((pid, int(base["Uic"]), str(base["AssetType"]), side, amount))
    return found


def _net_positions(broker, account_id, account_key, client_key):
    params = {"$top": 1000, "AccountKey": account_key,
              "FieldGroups": "NetPositionBase"}
    if client_key:
        params["ClientKey"] = client_key
    rows = _get_list(broker.client, "port/v1/netpositions", params)
    nonzero = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("NetPositionBase"), dict):
            raise RuntimeError("INVALID_NET_POSITION")
        base = row["NetPositionBase"]
        owner = str(base.get("PositionsAccount") or base.get("AccountId") or "")
        if owner and owner != account_id:
            raise RuntimeError("WRONG_NET_ACCOUNT")
        key = (int(base.get("Uic") or 0), str(base.get("AssetType") or ""))
        amount = float(base.get("AmountLong") or 0) - float(base.get("AmountShort") or 0)
        if (base.get("AmountLong") is None and base.get("AmountShort") is None):
            direction = str(base.get("OpeningDirection") or "").lower()
            raw = float(base.get("Amount") or 0)
            amount = raw if direction == "buy" else -raw if direction == "sell" else 0.0
            if raw and direction not in {"buy", "sell"}:
                raise RuntimeError("UNKNOWN_NET_DIRECTION")
        if not isfinite(amount) or key[0] <= 0 or not key[1]:
            raise RuntimeError("INVALID_NET_AMOUNT")
        if abs(amount) > 1e-9:
            if key in nonzero:
                raise RuntimeError("DUPLICATE_NET_PRODUCT")
            nonzero[key] = amount
    return nonzero


def _audit_for_pending(broker, account_key, client_key, pending, now):
    """Match Saxo's unique order ID or our exact ExternalReference.
    Return None on *no entry*, never interpret that alone as rejection.
    """
    since = _dt(pending["updated_at"]) - timedelta(minutes=5)
    params = {"$top": 500, "AccountKey": account_key, "EntryType": "Last",
              "FromDateTime": since.isoformat().replace("+00:00", "Z")}
    if client_key:
        params["ClientKey"] = client_key
    rows = _get_list(broker.client, "cs/v1/audit/orderactivities", params)
    ref = ("pgv3-" + str(pending["request_key"]))[-50:]
    order_id = str(pending.get("broker_order_id") or "")
    matches = [r for r in rows if isinstance(r, dict)
               and ((order_id and str(r.get("OrderId") or "") == order_id)
                    or str(r.get("ExternalReference") or "") == ref)]
    if len(matches) > 1 or (matches and
        (str(matches[0].get("AccountId") or "") == "" or
         str(matches[0].get("ExternalReference") or ref) != ref or
         str(matches[0].get("AccountId") or "") != str(pending.get("_account_id")))):
        raise RuntimeError("AMBIGUOUS_ORDER_AUDIT")
    return matches[0] if matches else None


def _retire_pending(pending, state, detail, *, account_id, uic, asset_type, db_path):
    """CAS guard retirement: a concurrent change must never be overwritten."""
    with connect(db_path) as db:
        cursor = db.execute(
            """UPDATE autotrader_v3_order_guard
               SET state=?,detail=?,updated_at=CURRENT_TIMESTAMP
               WHERE request_key=? AND account_id=? AND uic=? AND asset_type=?
                 AND state=? AND updated_at=?""",
            (state, detail[:200], pending["request_key"], account_id, int(uic),
             asset_type, pending["state"], pending["updated_at"]),
        )
        return cursor.rowcount == 1


def _unresolved_on_account(account_id, db_path):
    with connect(db_path) as db:
        rows = db.execute(
            """SELECT request_key,state,broker_order_id,detail,expected_inventory,
                      submitted_amount,submitted_side,updated_at,uic,asset_type
               FROM autotrader_v3_order_guard
               WHERE account_id=? AND state IN ('RESERVED','SUBMITTING','SUBMITTED','UNKNOWN')
               ORDER BY updated_at ASC""",
            (account_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def _auto_writes_enabled():
    return os.getenv("PRICEGAUGER_V3_EMERGENCY_AUTO_FLATTEN_ENABLED", "").strip().lower() in {"1", "true", "yes"}


def run_emergency_account_once_v1(account_id, broker, *, db_path="pricegauger.db", now=None):
    """One account transaction cycle. Only call inside its serial V3 worker lane.

    No strategy entries while latched. Only one broker mutation per invocation.
    By default this executes read-only and retains the latch.
    """
    incident = load_emergency_v1(account_id, db_path=db_path)
    if incident is None or incident.state not in ACTIVE:
        return "INACTIVE"
    current = _now(now)
    try:
        account_key, client_key = broker._account_context_exact(account_id)
        orders = _working_orders(broker, account_id, account_key)
        positions = _positions(broker, account_id, account_key, client_key)
        nets = _net_positions(broker, account_id, account_key, client_key)
        pending = _unresolved_on_account(account_id, db_path)
    except Exception as exc:
        _set(account_id, _error_state(exc), type(exc).__name__, db_path=db_path, now=current)
        return "BROKER_DOWN"

    if not _auto_writes_enabled():
        _set(account_id, "PAUSED", "AUTO_FLATTEN_NOT_ENABLED", db_path=db_path, now=current)
        return "PAUSED"

    # First resolve the durable order uncertainty; never submit another order
    # while a previous order can still be executed.
    for item in pending:
        item["_account_id"] = account_id
        try:
            activity = _audit_for_pending(broker, account_key, client_key, item, current)
        except Exception as exc:
            _set(account_id, "RESOLVING", type(exc).__name__, db_path=db_path, now=current)
            return "RESOLVING"
        uic, asset_type = item["uic"], item["asset_type"]
        age = (current - _dt(item["updated_at"])).total_seconds()
        pre = None
        try:
            quantity = float(item["submitted_amount"])
            expected = float(item["expected_inventory"])
            if quantity <= 0 or item["submitted_side"] not in {"Buy", "Sell"}:
                raise ValueError()
            pre = expected - (quantity if item["submitted_side"] == "Buy" else -quantity)
        except (TypeError, ValueError):
            pass
        actual = nets.get((int(uic), str(asset_type)), 0.0)
        same_working = any(int(o.get("Uic") or -1) == int(uic)
                           and str(o.get("AssetType") or "") == str(asset_type)
                           for o in orders)
        if activity:
            status = str(activity.get("Status") or "")
            sub = str(activity.get("SubStatus") or "")
            if status == "FinalFill" and sub in {"", "Confirmed"} and abs(actual-expected) <= 1e-8:
                if _retire_pending(item,"RECONCILED","EMERGENCY_BROKER_FILL_CONFIRMED",
                                   account_id=account_id,uic=uic,asset_type=asset_type,db_path=db_path):
                    return "RESOLVED"
            if status in {"Cancelled","Expired"} and sub == "Confirmed" and pre is not None and abs(actual-pre) <= 1e-8 and not same_working and not float(activity.get("FilledAmount") or 0):
                if _retire_pending(item,"REJECTED","EMERGENCY_BROKER_CANCEL_CONFIRMED",
                                   account_id=account_id,uic=uic,asset_type=asset_type,db_path=db_path):
                    return "RESOLVED"
            _set(account_id,"RESOLVING","BROKER_ORDER_STILL_UNRESOLVED",
                 db_path=db_path,now=current)
            return "RESOLVING"
        # An unobserved order is not a rejected order: do NOT release UNKNOWN
        # or SUBMITTING just because two independent GETs found no matching id.
        # Broker-side order settlement needs positive terminal confirmation.
        if item["state"] == "RESERVED" and age >= GRACE_SECONDS and pre is not None and abs(actual-pre) <= 1e-8 and not orders:
            if _retire_pending(item,"REJECTED","EMERGENCY_NEVER_SUBMITTED_RESERVED",
                               account_id=account_id,uic=uic,asset_type=asset_type,db_path=db_path):
                return "RESOLVED"
        _set(account_id,"RESOLVING","NO_VERIFIABLE_BROKER_ORDER_RESULT",
             db_path=db_path,now=current)
        return "RESOLVING"

    if orders:
        first = orders[0]
        order_id = str(first.get("OrderId") or "")
        if not order_id:
            _set(account_id,"RESOLVING","WORKING_ORDER_WITHOUT_ID",db_path=db_path,now=current)
            return "RESOLVING"
        from autotrader_execution_guard_v1 import _delete_order_once_v1
        _set(account_id,"CANCELLING","CANCELLING_ACCOUNT_WORKING_ORDER",db_path=db_path,now=current)
        try:
            _delete_order_once_v1(broker.client,account_key=account_key,order_id=order_id)
        except Exception as exc:
            _set(account_id,_error_state(exc),type(exc).__name__,db_path=db_path,now=current)
        return "CANCELLING"

    if positions or nets:
        # A true full-account flatten must not guess what netting mode Saxo
        # applies. The initial pilot permits only an unambiguous one-position
        # per product with its exact net inventory equal to that position.
        by_product = {}
        for pid, uic, asset_type, side, amount in positions:
            by_product.setdefault((uic,asset_type),[]).append((pid,side,amount))
        if not positions or any(len(p) != 1 for p in by_product.values()) or set(by_product) != set(nets):
            _set(account_id,"RESOLVING","GROSS_NET_POSITION_MISMATCH",db_path=db_path,now=current)
            return "RESOLVING"
        for (uic,asset_type), group in by_product.items():
            pid,side,amount = group[0]
            actual = nets[(uic,asset_type)]
            signed = amount if side == "buy" else -amount
            if abs(signed-actual) > 1e-8:
                _set(account_id,"RESOLVING","NET_POSITION_CHANGED",db_path=db_path,now=current)
                return "RESOLVING"
        (uic,asset_type), group = sorted(by_product.items())[0]
        pid, side, amount = group[0]
        request_key = str(uuid5(NAMESPACE_URL, f"pgv3:emergency:{account_id}:{pid}:{side}:{amount:.10g}"))
        buy_sell = "Sell" if side == "buy" else "Buy"
        inserted = reserve(request_key=request_key,trader_id="EMERGENCY:"+account_id,
                           account_id=account_id,uic=uic,asset_type=asset_type,
                           expected_inventory=0.0,submitted_amount=amount,submitted_side=buy_sell,
                           db_path=db_path,idempotent=True)
        if not inserted:
            _set(account_id,"RESOLVING","EMERGENCY_RESERVATION_CONFLICT",db_path=db_path,now=current)
            return "RESOLVING"
        if not claim_reserved_for_submission_v3(request_key=request_key,db_path=db_path):
            return "RESOLVING"
        order = SaxoOrderRequest(
            account_key=account_key,
            instrument=SaxoInstrument(asset="",uic=uic,asset_type=asset_type),
            amount=amount,buy_sell=buy_sell,
            external_reference=("pgv3-"+request_key)[-50:])
        _set(account_id,"CLOSING","EMERGENCY_CLOSING_CONFIRMED_EXPOSURE",db_path=db_path,now=current)
        try:
            response = broker.place_order(order,confirm_live=True)
            order_id = str(response.get("OrderId") or "") if isinstance(response,dict) else ""
            if not order_id:
                mark(request_key=request_key,state="UNKNOWN",detail="EMERGENCY_CLOSE_NO_ORDER_ID",db_path=db_path)
                return "UNKNOWN"
            mark(request_key=request_key,state="SUBMITTED",broker_order_id=order_id,
                 detail="EMERGENCY_CLOSE_BROKER_ACCEPTED",db_path=db_path)
            return "SUBMITTED"
        except Exception as exc:
            mark(request_key=request_key,state="UNKNOWN",
                 detail="EMERGENCY_CLOSE_"+type(exc).__name__,db_path=db_path)
            _set(account_id,"BROKER_DOWN",type(exc).__name__,db_path=db_path,now=current)
            return "UNKNOWN"

    # Two distinct broker snapshots and a minimum interval are necessary;
    # each run also required complete account-scoped orders/positions/net reads.
    seen = incident.flat_seen_at
    if seen is None:
        _set(account_id,"VERIFYING","FIRST_BROKER_FLAT_SNAPSHOT",db_path=db_path,
             now=current,flat_seen_at=current.isoformat())
        return "VERIFYING"
    if (current - _dt(seen)).total_seconds() < FLAT_CONFIRM_SECONDS:
        return "VERIFYING"
    _set(account_id,"RESUMED","TWO_BROKER_FLAT_SNAPSHOTS",db_path=db_path,now=current)
    return "RESUMED"


__all__ = ["AccountEmergencyV1","activate_emergency_v1","emergency_active_v1",
           "load_emergency_v1","run_emergency_account_once_v1","ensure_schema_v1",
           "should_start_emergency_v1", "active_emergency_accounts_v1"]
