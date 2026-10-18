"""Read-only Saxo account-history ingestion for V3 fleet statistics.

Only GET /hist resources; never touch Saxo orders, runtime targets or live authority.
Saxo account-wide P/L is NOT attributable to a single V3 strategy when the
account has manual trades, other products, cash flows, or strategy switches.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from math import isfinite

from database import connect

FIELD_GROUPS = "Balance_AccountValue,Balance_CashTransfer,TimeWeighted_Accumulated"
SOURCE = "SAXO_HIST_V4_EOD"
BACKFILL_DAYS = 12  # covers 12–16 October with prior NAV as of 9 October
MIN_SYNC_GAP = timedelta(hours=6)
FAIL_SYNC_GAP = timedelta(minutes=45)


def _row(row, key, index):
    return row[key] if isinstance(row, dict) else row[index]


def _number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        val = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return val if isfinite(val) else None


def _date(value):
    if not value:
        raise ValueError("Saxo history date missing")
    return date.fromisoformat(str(value)[:10])


def _points(parent, key):
    values = parent.get(key, []) if isinstance(parent, dict) else []
    if not isinstance(values, list):
        raise ValueError("Saxo time-series has invalid shape")
    result = {}
    for point in values:
        if not isinstance(point, dict):
            raise ValueError("Saxo time-series point must be an object")
        value = _number(point.get("Value"))
        day = _date(point.get("Date"))
        if value is None:
            raise ValueError("Saxo time-series point has invalid value")
        result[day] = value
    return result


def normalize_timeseries_v1(payload):
    """Daily EOD NAV change less reported cash transfers (not realized trade P/L).

    Saxo time-weighted cumulative return is a separate source; never reconstruct
    returns by subtracting cash flows and calling the result a broker return.
    """
    if not isinstance(payload, dict):
        raise ValueError("Saxo performance payload must be an object")
    balance = payload.get("Balance") or {}
    weighted = payload.get("TimeWeighted") or {}
    nav = _points(balance, "AccountValue")
    cash = _points(balance, "CashTransfer")
    accumulated = _points(weighted, "Accumulated")
    if not nav:
        raise ValueError("Saxo EOD account-value time series was empty")
    result = []
    previous_nav = previous_acc = None
    for day in sorted(nav):
        value = nav[day]
        transfers = cash.get(day, 0.0)
        nav_delta = None if previous_nav is None else value - previous_nav - transfers
        acc = accumulated.get(day)
        twr_day = None
        if previous_acc is not None and acc is not None and 1 + previous_acc > 0:
            twr_day = (1 + acc) / (1 + previous_acc) - 1
        result.append({
            "day": day.isoformat(),
            "nav": value,
            "cash_transfer": transfers,
            "nav_change_ex_cash": nav_delta,
            "saxo_accumulated_twr": acc,
            "daily_twr": twr_day,
            "source": SOURCE,
        })
        previous_nav = value
        previous_acc = acc
    return result


def _pages(client, path, base_params, *, max_pages=40, page_size=500):
    """Never follow Saxo-supplied URLs; paginate the fixed endpoint by skip."""
    all_rows = []
    for page in range(max_pages):
        params = {**base_params, "$top": page_size, "$skip": page * page_size}
        payload = client._get(path, params=params)
        rows = payload.get("Data")
        if not isinstance(rows, list):
            raise ValueError("Saxo historical feed is missing Data list")
        all_rows.extend(rows)
        if len(rows) < page_size and not payload.get("__next"):
            return all_rows
        if not rows:
            raise ValueError("Saxo history indicates more pages but supplied no rows")
    raise ValueError("Saxo historical feed exceeds safe pagination limit")


def normalize_transactions_v1(rows, account_id):
    """Persist minimal broker evidence; exclude IBAN/owner/free-text metadata."""
    result = []
    for item in rows:
        if not isinstance(item, dict):
            raise ValueError("Invalid Saxo transaction row")
        if str(item.get("AccountId") or "") != str(account_id):
            raise ValueError("Saxo transaction account boundary mismatch")
        when = str(item.get("Date") or "")
        _date(when)
        key = sha256(("tx:" + account_id + ":" + ":".join(
            str(item.get(k) or "") for k in ("BkRecordId", "BookingId", "TradeId",
                                             "PositionId", "TransactionType", "Date")
        )).encode()).hexdigest()
        result.append({
            "key": key, "day": _date(when).isoformat(),
            "kind": str(item.get("TransactionType") or ""),
            "trade_id": str(item.get("TradeId") or ""),
            "realized_pnl": _number(item.get("RealizedPnL")),
            "total_cost": _number(item.get("TotalCost")),
            "currency": str(item.get("Currency") or ""),
        })
    return result


def normalize_positions_v1(rows, account_id):
    result = []
    for item in rows:
        if not isinstance(item, dict):
            raise ValueError("Invalid Saxo historical position")
        if str(item.get("AccountId") or "") != str(account_id):
            raise ValueError("Saxo historical position account boundary mismatch")
        closed = str(item.get("ExecutionTimeClose") or item.get("ClosingTradeDate") or "")
        _date(closed)
        key = sha256(("closed:" + account_id + ":" + ":".join(
            str(item.get(k) or "") for k in ("PositionId", "ExecutionTimeOpen",
                                             "ExecutionTimeClose", "Uic", "Amount")
        )).encode()).hexdigest()
        result.append({
            "key": key, "day": _date(closed).isoformat(),
            "uic": str(item.get("Uic") or ""),
            "amount": _number(item.get("Amount")),
            "opened_at": str(item.get("ExecutionTimeOpen") or ""),
            "closed_at": closed,
            "pnl": _number(item.get("ProfitLoss")),
        })
    return result


def ensure_history_tables_v1(db_path="pricegauger.db"):
    with connect(db_path) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS pg_v3_saxo_account_daily(
          account_id TEXT NOT NULL,day TEXT NOT NULL,account_currency TEXT NOT NULL,
          nav DOUBLE PRECISION NOT NULL,cash_transfer DOUBLE PRECISION NOT NULL,
          nav_change_ex_cash DOUBLE PRECISION,saxo_accumulated_twr DOUBLE PRECISION,
          daily_twr DOUBLE PRECISION,source TEXT NOT NULL,
          updated_at TEXT NOT NULL,PRIMARY KEY(account_id,day))""")
        db.execute("""CREATE TABLE IF NOT EXISTS pg_v3_saxo_history_transactions(
          account_id TEXT NOT NULL,row_key TEXT NOT NULL,day TEXT NOT NULL,
          kind TEXT,trade_id TEXT,realized_pnl DOUBLE PRECISION,
          total_cost DOUBLE PRECISION,currency TEXT,
          updated_at TEXT NOT NULL,PRIMARY KEY(account_id,row_key))""")
        db.execute("""CREATE TABLE IF NOT EXISTS pg_v3_saxo_history_closed(
          account_id TEXT NOT NULL,row_key TEXT NOT NULL,day TEXT NOT NULL,
          uic TEXT,amount DOUBLE PRECISION,opened_at TEXT,closed_at TEXT,
          pnl DOUBLE PRECISION,updated_at TEXT NOT NULL,
          PRIMARY KEY(account_id,row_key))""")
        db.execute("""CREATE TABLE IF NOT EXISTS pg_v3_saxo_history_sync(
          account_id TEXT PRIMARY KEY,last_attempt TEXT NOT NULL,
          last_success TEXT,status TEXT NOT NULL,detail TEXT NOT NULL)""")


def _due(account_id, now, db_path):
    with connect(db_path) as db:
        row = db.execute(
            "SELECT last_attempt,last_success,status FROM pg_v3_saxo_history_sync WHERE account_id=?",
            (account_id,),
        ).fetchone()
    if row is None:
        return True
    last = datetime.fromisoformat(str(_row(row, "last_attempt", 0)))
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    gap = MIN_SYNC_GAP if str(_row(row, "status", 2)) == "OK" else FAIL_SYNC_GAP
    return now - last >= gap


def _status(account_id, now, status, detail, db_path):
    with connect(db_path) as db:
        db.execute("""INSERT INTO pg_v3_saxo_history_sync(
            account_id,last_attempt,last_success,status,detail)
          VALUES(?,?,?,?,?)
          ON CONFLICT(account_id) DO UPDATE SET
            last_attempt=excluded.last_attempt,
            last_success=CASE WHEN excluded.status='OK'
              THEN excluded.last_success ELSE pg_v3_saxo_history_sync.last_success END,
            status=excluded.status,detail=excluded.detail""",
          (account_id, now.isoformat(), now.isoformat() if status == "OK" else None,
           status, detail))


def sync_account_v1(*, broker, account, from_day, through_day, db_path="pricegauger.db"):
    """All remote requests are GET; persist only a complete per-account snapshot."""
    account_id = str(account.get("AccountId") or "").strip()
    account_key = str(account.get("AccountKey") or "").strip()
    client_key = str(account.get("ClientKey") or "").strip()
    if not account_id or not account_key or not client_key:
        raise ValueError("Saxo account lacks complete identity")
    params = {"ClientKey": client_key, "AccountKey": account_key,
              "FromDate": from_day.isoformat(), "ToDate": through_day.isoformat()}
    client = broker.client
    series = client._get("hist/v4/performance/timeseries",
                         params={**params, "FieldGroups": FIELD_GROUPS})
    days = normalize_timeseries_v1(series)
    transactions = normalize_transactions_v1(
        _pages(client, "hist/v1/transactions", {
            "ClientKey": client_key, "AccountKeys": account_key,
            "FromDate": from_day.isoformat(), "ToDate": through_day.isoformat(),
        }), account_id)
    closed = normalize_positions_v1(
        _pages(client, "hist/v3/positions/" + client_key, {
            "AccountKey": account_key,
            "FromDate": from_day.isoformat(), "ToDate": through_day.isoformat(),
        }), account_id)
    stamp = datetime.now(timezone.utc).isoformat()
    currency = str(account.get("Currency") or account.get("CurrencyCode") or "")
    with connect(db_path) as db:
        for day in days:
            db.execute("""INSERT INTO pg_v3_saxo_account_daily(
              account_id,day,account_currency,nav,cash_transfer,nav_change_ex_cash,
              saxo_accumulated_twr,daily_twr,source,updated_at)
              VALUES(?,?,?,?,?,?,?,?,?,?)
              ON CONFLICT(account_id,day) DO UPDATE SET
                account_currency=excluded.account_currency,nav=excluded.nav,
                cash_transfer=excluded.cash_transfer,
                nav_change_ex_cash=excluded.nav_change_ex_cash,
                saxo_accumulated_twr=excluded.saxo_accumulated_twr,
                daily_twr=excluded.daily_twr,updated_at=excluded.updated_at""",
              (account_id,day["day"],currency,day["nav"],day["cash_transfer"],
               day["nav_change_ex_cash"],day["saxo_accumulated_twr"],day["daily_twr"],
               day["source"],stamp))
        for tx in transactions:
            db.execute("""INSERT INTO pg_v3_saxo_history_transactions(
              account_id,row_key,day,kind,trade_id,realized_pnl,total_cost,currency,updated_at)
              VALUES(?,?,?,?,?,?,?,?,?)
              ON CONFLICT(account_id,row_key) DO UPDATE SET
                realized_pnl=excluded.realized_pnl,total_cost=excluded.total_cost,
                currency=excluded.currency,updated_at=excluded.updated_at""",
              (account_id,tx["key"],tx["day"],tx["kind"],tx["trade_id"],
               tx["realized_pnl"],tx["total_cost"],tx["currency"],stamp))
        for position in closed:
            db.execute("""INSERT INTO pg_v3_saxo_history_closed(
              account_id,row_key,day,uic,amount,opened_at,closed_at,pnl,updated_at)
              VALUES(?,?,?,?,?,?,?,?,?)
              ON CONFLICT(account_id,row_key) DO UPDATE SET
                pnl=excluded.pnl,updated_at=excluded.updated_at""",
              (account_id,position["key"],position["day"],position["uic"],
               position["amount"],position["opened_at"],position["closed_at"],
               position["pnl"],stamp))
    return len(days),len(transactions),len(closed)


def run_saxo_history_sync_v1(*, db_path="pricegauger.db", now=None):
    """Bounded, low-frequency worker cycle, entirely independent of LIVE."""
    from autotrader_v3_instance_registry_v1 import load_v3_instances_v1
    from autotrader_v3_live_saxo_v1 import configured_live_pilot_client_v3
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("timezone-aware now required")
    through_day = current.date() - timedelta(days=1)  # settled EOD only
    from_day = through_day - timedelta(days=BACKFILL_DAYS)
    ensure_history_tables_v1(db_path)
    broker = configured_live_pilot_client_v3()
    if broker is None:
        return {"status": "NO_LIVE_READ_CONNECTION"}
    by_id = {str(a.get("AccountId") or ""): a for a in broker.accounts()
             if isinstance(a, dict)}
    results = {}
    for instance in load_v3_instances_v1(db_path=db_path):
        aid = instance.account_id
        if aid in results or not _due(aid,current,db_path):
            continue
        account = by_id.get(aid)
        if not account:
            _status(aid,current,"ERROR","MISSING_ACCOUNT_IDENTITY",db_path)
            results[aid] = "MISSING_ACCOUNT_IDENTITY"
            continue
        try:
            results[aid] = sync_account_v1(
                broker=broker,account=account,from_day=from_day,
                through_day=through_day,db_path=db_path)
        except Exception as exc:
            _status(aid,current,"ERROR",type(exc).__name__,db_path)
            results[aid] = "ERROR:" + type(exc).__name__
        else:
            _status(aid,current,"OK","SAXO_EOD",db_path)
    return results


def load_saxo_history_stats_v1(*, db_path="pricegauger.db", from_day=None):
    ensure_history_tables_v1(db_path)
    from_day = from_day or (date.today() - timedelta(days=30))
    with connect(db_path) as db:
        days = db.execute("""SELECT d.account_id,d.day,d.account_currency,
              d.nav,d.cash_transfer,d.nav_change_ex_cash,d.daily_twr,d.source,
              s.last_success,s.status
              FROM pg_v3_saxo_account_daily d
              LEFT JOIN pg_v3_saxo_history_sync s ON s.account_id=d.account_id
              WHERE d.day>=? ORDER BY d.day DESC,d.account_id""",
              (from_day.isoformat(),)).fetchall()
        tx = db.execute("""SELECT account_id,day,currency,
              SUM(realized_pnl) AS realized_pnl,
              SUM(total_cost) AS total_cost,
              COUNT(*) AS transactions
              FROM pg_v3_saxo_history_transactions WHERE day>=?
              GROUP BY account_id,day,currency""",
              (from_day.isoformat(),)).fetchall()
        closed = db.execute("""SELECT account_id,day,COUNT(*) AS closed_positions
              FROM pg_v3_saxo_history_closed WHERE day>=?
              GROUP BY account_id,day""",
              (from_day.isoformat(),)).fetchall()
    to_dict = lambda row: dict(row)
    return {
        "days": [to_dict(r) for r in days],
        "transactions": [to_dict(r) for r in tx],
        "closed_positions": [to_dict(r) for r in closed],
    }


__all__ = [
    "normalize_timeseries_v1", "normalize_transactions_v1", "normalize_positions_v1",
    "sync_account_v1", "run_saxo_history_sync_v1", "load_saxo_history_stats_v1",
]
