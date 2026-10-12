"""Research-only, capped 1 Hz Saxo BBO capture. Never makes broker requests.

Quotes are written only when the Saxo streaming adapter reports *tradable*
undelayed bid AND ask for the exact Tech100 UIC. No interpolated prices.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from pathlib import Path

from database import connect


def _utc(value):
    parsed=value if isinstance(value,datetime) else datetime.fromisoformat(
        str(value).replace("Z","+00:00"))
    if parsed.tzinfo is None:
        parsed=parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def ensure_hyper_quote_schema(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS lsim_hyper_quotes_1s (
            provider_uic INTEGER NOT NULL,
            quote_at TEXT NOT NULL,
            market_name TEXT NOT NULL,
            asset_type TEXT NOT NULL,
            bid REAL NOT NULL,
            ask REAL NOT NULL,
            received_at TEXT NOT NULL,
            PRIMARY KEY(provider_uic,quote_at)
        );
        CREATE INDEX IF NOT EXISTS lsim_hyper_quotes_time
            ON lsim_hyper_quotes_1s(quote_at);
    """)


class HyperQuoteRecorder:
    """A single broker-free SQLite/Postgres upsert per valid distinct second."""
    def __init__(self,db_path="pricegauger.db"):
        self.db_path=str(db_path)
        self._last_seen={}
        with connect(self.db_path) as db:
            ensure_hyper_quote_schema(db)

    def observe(self,quote,*,tradable:bool,now=None)->bool:
        if not tradable or quote.uic is None:
            return False
        name=str(quote.market or "")
        if not any(word in name.upper() for word in ("TECH","NAS")):
            return False
        if quote.bid is None or quote.ask is None:
            return False
        try:
            bid,ask=float(quote.bid),float(quote.ask)
            stamp=_utc(quote.observed_at)
            instant=_utc(now or datetime.now(timezone.utc))
        except (TypeError,ValueError,OverflowError):
            return False
        if not all(math.isfinite(v) and v>0 for v in (bid,ask)) or ask<bid:
            return False
        # Guard against delayed Saxo quotes, future timestamps and stale replays.
        lag=(instant-stamp).total_seconds()
        if lag < -2 or lag > 5:
            return False
        second=stamp.replace(microsecond=0).isoformat()
        uic=int(quote.uic)
        if self._last_seen.get(uic)==second:
            return False
        with connect(self.db_path) as db:
            result=db.execute("""
                INSERT INTO lsim_hyper_quotes_1s(
                    provider_uic,quote_at,market_name,asset_type,bid,ask,received_at)
                VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(provider_uic,quote_at) DO NOTHING
            """,(uic,second,name,str(quote.asset_type),bid,ask,instant.isoformat()))
        self._last_seen[uic]=second
        return result.rowcount>0


def hyper_quote_status(*,db_path="pricegauger.db"):
    with connect(db_path) as db:
        ensure_hyper_quote_schema(db)
        return [dict(row) for row in db.execute("""
            SELECT provider_uic,market_name,MAX(quote_at) AS last_quote,
                   COUNT(*) AS captured_quotes
            FROM lsim_hyper_quotes_1s
            GROUP BY provider_uic,market_name
            ORDER BY provider_uic
        """).fetchall()]
