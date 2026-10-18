"""Regression: duplicate market bars must not rewrite PostgreSQL/SQLite rows.

Conditional UPSERT reduces redundant WAL/locks and legacy updated_at churn
during repeated backfill or gap repair, without losing corrected candles.
These tests isolate SQLite to avoid changing or reading LIVE risk tables.
"""
from dataclasses import replace
import sqlite3

import canonical_market_bars_v2 as canonical
import realtime_market_data as realtime
from database import connect
from instrument_registry_v2 import InstrumentSourceV2


def fake_bar():
    return realtime.RealtimeBar1m(
        market="Gold",bar_time="2026-10-18T01:23:00+00:00",
        open=100.0,high=101.0,low=99.0,close=100.5,
        sample_count=4,provider="Saxo OpenAPI",uic=11,
        asset_type="CfdOnFutures",symbol="Gold",volume=None,
    )


def test_canonical_repeat_bar_skips_update_but_corrections_and_quality_write(monkeypatch,tmp_path):
    path=str(tmp_path/"canonical.sqlite")
    monkeypatch.setattr(canonical,"connect",lambda p:connect(p,force_sqlite=True))
    with sqlite3.connect(path) as db:
        db.executescript("""
            CREATE TABLE pg_v2_market_bars_1m(
                instrument_id INTEGER NOT NULL,bar_time TEXT NOT NULL,
                open REAL,high REAL,low REAL,close REAL,volume REAL,
                quality_flags INTEGER NOT NULL,
                PRIMARY KEY(instrument_id,bar_time)
            );
            CREATE TABLE update_counter(n INTEGER);
            INSERT INTO update_counter(n) VALUES(0);
            CREATE TRIGGER count_bar_updates AFTER UPDATE ON pg_v2_market_bars_1m
            BEGIN UPDATE update_counter SET n=n+1; END;
        """)
    source=InstrumentSourceV2(
        market_id=1,market_name="Gold",instrument_id=19,
        instrument_type="CFD",display_name="Gold",provider="Saxo",
        provider_instrument_id="11",
    )
    store=canonical.CanonicalMarketBarStoreV2(path)
    bar=fake_bar()
    store.save(source=source,bar=bar,quality_flags=1)
    store.save(source=source,bar=bar,quality_flags=1)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT n FROM update_counter").fetchone()[0]==0
    # Corrections to candle values must update stored history immediately.
    corrected=replace(bar,close=100.9,volume=0.0)
    store.save(source=source,bar=corrected,quality_flags=1)
    store.save(source=source,bar=corrected,quality_flags=2)
    store.save(source=source,bar=corrected,quality_flags=2)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT n FROM update_counter").fetchone()[0]==2
        assert db.execute(
            "SELECT close,volume,quality_flags FROM pg_v2_market_bars_1m"
        ).fetchone()==(100.9,0.0,2)


def test_legacy_backfill_duplicate_does_not_touch_updated_at_or_issue_update(monkeypatch,tmp_path):
    path=str(tmp_path/"legacy.sqlite")
    monkeypatch.setattr(realtime,"connect",lambda p:connect(p,force_sqlite=True))
    monkeypatch.setattr(realtime,"using_postgres",lambda:False)
    store=realtime.RealtimeMarketDataStore(path)
    with sqlite3.connect(path) as db:
        db.executescript("""
            CREATE TABLE update_counter(n INTEGER);
            INSERT INTO update_counter(n) VALUES(0);
            CREATE TRIGGER count_legacy_updates AFTER UPDATE ON realtime_bars_1m
            BEGIN UPDATE update_counter SET n=n+1; END;
        """)
    bar=fake_bar()
    store.save_bar(bar)
    with sqlite3.connect(path) as db:
        db.execute(
            "UPDATE realtime_bars_1m SET updated_at=?",
            ("2026-01-01 00:00:00",),
        )
        db.execute("UPDATE update_counter SET n=0")
    store.save_bar(bar)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT n FROM update_counter").fetchone()[0]==0
        assert db.execute("SELECT updated_at FROM realtime_bars_1m").fetchone()[0]=="2026-01-01 00:00:00"
    store.save_bar(replace(bar,high=105.0))
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT n FROM update_counter").fetchone()[0]==1
        assert '"high": 105.0' in db.execute("SELECT payload_json FROM realtime_bars_1m").fetchone()[0]
