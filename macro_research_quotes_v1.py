"""Research-only archive of source-timestamped delayed and live Saxo BBO.

Never read by trading engines. Preserve source and real receipt times;
do not subtract the nominal delay from an already delayed source timestamp.
"""
from datetime import datetime, timezone
from math import isfinite

from database import connect
from macro_release_lag_observer_v1 import market_group, utc


def ensure_research_schema(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS macro_research_quotes_1s (
            provider_uic INTEGER NOT NULL,
            quote_at TEXT NOT NULL,
            received_at TEXT NOT NULL,
            market_name TEXT NOT NULL,
            asset_type TEXT NOT NULL,
            bid REAL NOT NULL,
            ask REAL NOT NULL,
            delay_minutes REAL NOT NULL,
            price_type_bid TEXT NOT NULL,
            price_type_ask TEXT NOT NULL,
            PRIMARY KEY(provider_uic,quote_at)
        );
        CREATE INDEX IF NOT EXISTS macro_research_quotes_time
            ON macro_research_quotes_1s(quote_at);
    """)


class MacroResearchRecorder:
    def __init__(self, db_path="pricegauger.db"):
        self.db_path = db_path
        self.last_seen = {}
        with connect(db_path) as db:
            ensure_research_schema(db)

    def observe(self, quote, *, provider_at, received_at, delay, price_type_bid="", price_type_ask=""):
        if market_group(quote.market) not in ("Gull", "Sølv", "US500"):
            return False
        if provider_at is None or delay is None or quote.uic is None:
            return False
        try:
            source, receipt = utc(provider_at), utc(received_at)
            delay, bid, ask = float(delay), float(quote.bid), float(quote.ask)
            age = (receipt - source).total_seconds()
        except (TypeError, ValueError, OverflowError):
            return False
        if not all(isfinite(x) for x in (delay, bid, ask)) or not (0 <= delay <= 60 and 0 < bid <= ask):
            return False
        # Unknown timestamp semantics, stale replay, and receipt-time fallback
        # must not masquerade as source-time market observations.
        if not -2 <= age - delay * 60 <= 15:
            return False
        uic = int(quote.uic)
        second = source.replace(microsecond=0).isoformat()
        if self.last_seen.get(uic) == second:
            return False
        with connect(self.db_path) as db:
            result = db.execute("""
                INSERT INTO macro_research_quotes_1s
                    (provider_uic,quote_at,received_at,market_name,asset_type,
                     bid,ask,delay_minutes,price_type_bid,price_type_ask)
                VALUES(?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(provider_uic,quote_at) DO NOTHING
            """, (uic,second,receipt.isoformat(),quote.market,str(quote.asset_type),
                  bid,ask,delay,str(price_type_bid or ""),str(price_type_ask or "")))
        self.last_seen[uic] = second
        return result.rowcount > 0


def research_rows(start, end, *, db_path="pricegauger.db"):
    """Actual source-time archive; no synthetic data and no live authority."""
    with connect(db_path) as db:
        ensure_research_schema(db)
        return [dict(r) for r in db.execute("""
            SELECT * FROM macro_research_quotes_1s
            WHERE quote_at>=? AND quote_at<=?
            ORDER BY quote_at LIMIT 30001
        """, (utc(start).isoformat(),utc(end).isoformat())).fetchall()]


def source_time_rows(rows):
    """Copies for retrospective analysis only. Raw receipt times stay intact."""
    return [dict(r, received_at=r["quote_at"]) for r in rows]
