"""Read-only data binding and as-of correctness: no Saxo or AI calls."""
from datetime import datetime, timedelta, timezone
import json
import sqlite3
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from tempfile import TemporaryDirectory
from pathlib import Path

from canonical_market_bars_v2 import CanonicalMarketBarV2, QUALITY_BACKFILL, QUALITY_REALTIME
from cross_market_state import CrossMarketStateSnapshot
from database import connect
from instrument_registry_v2 import InstrumentSourceV2
from tech100_four_channel_synthesis_v1 import MACRO_NEWS, TECH_NEWS
from tech100_synthesis_data_v1 import (
    PRICE_CHANNELS, PriceSourceWindow, aligned_price_moves,
    load_archived_news, load_archived_gdelt_news, load_archived_yield_snapshot,
    load_canonical_prices, resolve_exact_subscriptions, source_candidates,
    yield_feed_status,
)


NOW = datetime(2026, 11, 20, 14, 0, tzinfo=timezone.utc)


def source(name, uic, instrument_id):
    market = {"Tech100": "US Tech 100 NAS", "Gold": "Gold", "Brent": "Brent", "DXY": "US Dollar Index"}[name]
    return InstrumentSourceV2(1, market, instrument_id, "CFD", market,
                              "saxo", uic, "CfdOnIndex")


SOURCES = [source("Tech100", "4912", 10), source("Gold", "100", 20),
           source("Brent", "200", 30), source("DXY", "300", 40)]


class NavigationRegistrationTests(unittest.TestCase):
    def test_tech100_synthesis_page_is_visible_in_navigation(self):
        from navigation_config import PAGE_GROUPS
        synthesis = [page for page in PAGE_GROUPS["Analyse"]
                     if page["page"] == "pages/0_Tech100_Syntese.py"]
        self.assertEqual(len(synthesis), 1)
        self.assertEqual(synthesis[0]["url_path"], "Tech100_Syntese")


def bar(item, *, minutes_ago, close=100, quality=QUALITY_REALTIME):
    stamp = NOW - timedelta(minutes=minutes_ago)
    return CanonicalMarketBarV2(item.instrument_id, item.market_id, item.market_name,
                                 stamp.isoformat(), close, close, close, close,
                                 None, quality)


class ExactMarketIdentityTests(unittest.TestCase):
    def test_exact_subscriptions_and_ambiguity(self):
        result = resolve_exact_subscriptions(SOURCES)
        self.assertEqual(set(result), set(PRICE_CHANNELS))
        self.assertEqual(result["Tech100"].provider_instrument_id, "4912")
        self.assertEqual([item.provider_instrument_id for item in source_candidates(SOURCES)["Gold"]], ["100"])
        with self.assertRaisesRegex(LookupError, "Gold"):
            resolve_exact_subscriptions(SOURCES + [source("Gold", "101", 21)])
        result = resolve_exact_subscriptions(SOURCES + [source("Gold", "101", 21)],
                                             selected_uics={"Gold": "101"})
        self.assertEqual(result["Gold"].instrument_id, 21)

    def test_wrong_tech100_uic_rejected_even_if_market_name_matches(self):
        bad = [source("Tech100", "9999", 10)] + SOURCES[1:]
        with self.assertRaisesRegex(LookupError, "Tech100"):
            resolve_exact_subscriptions(bad)

    def test_dxy_is_required_and_source_is_unambiguous(self):
        with self.assertRaisesRegex(LookupError, "DXY"):
            resolve_exact_subscriptions(SOURCES[:-1])
        with self.assertRaisesRegex(LookupError, "DXY"):
            resolve_exact_subscriptions(SOURCES + [source("DXY", "301", 41)])
        chosen = resolve_exact_subscriptions(SOURCES + [source("DXY", "301", 41)],
                                             selected_uics={"DXY": "301"})
        self.assertEqual(chosen["DXY"].instrument_id, 41)

    def test_canonical_loader_only_uses_completed_source_bars(self):
        by_instrument = {item.instrument_id: [bar(item, minutes_ago=2),
                                               bar(item, minutes_ago=1),
                                               bar(item, minutes_ago=0)]
                         for item in SOURCES}
        fake_store = SimpleNamespace(load_instrument_range=lambda *, instrument_id, **_: by_instrument[instrument_id])
        with patch("tech100_synthesis_data_v1.CanonicalMarketBarStoreV2", return_value=fake_store):
            result = load_canonical_prices(at=NOW, lookback_minutes=2,
                                           subscriptions=SOURCES)
        for window in result.values():
            self.assertEqual(len(window.bars), 2)
            self.assertTrue(all(datetime.fromisoformat(row.bar_time) < NOW for row in window.bars))

    def test_exact_minute_alignment_no_gap_or_stale_gold(self):
        valid = {name: PriceSourceWindow(item, tuple(bar(item, minutes_ago=minutes, close=100 + 6 - minutes)
                                                    for minutes in range(6, 0, -1)))
                 for name, item in zip(PRICE_CHANNELS, SOURCES)}
        good = aligned_price_moves(valid, at=NOW, lookback_minutes=5)
        self.assertEqual(good.status, "VALID")
        self.assertAlmostEqual(good.returns_pct["Gold"], 5.0)
        self.assertAlmostEqual(good.returns_pct["DXY"], 5.0)
        stale_gold = dict(valid)
        stale_gold["Gold"] = PriceSourceWindow(SOURCES[1], valid["Gold"].bars[:-1])
        self.assertEqual(aligned_price_moves(stale_gold, at=NOW, lookback_minutes=5).status, "INCOMPLETE")
        backfilled = dict(valid)
        rows = list(valid["Brent"].bars)
        row = rows[-1]
        rows[-1] = CanonicalMarketBarV2(row.instrument_id, row.market_id, row.market_name,
                                        row.bar_time, row.open, row.high, row.low, row.close,
                                        row.volume, QUALITY_BACKFILL)
        backfilled["Brent"] = PriceSourceWindow(SOURCES[2], tuple(rows))
        self.assertEqual(aligned_price_moves(backfilled, at=NOW, lookback_minutes=5).status, "INCOMPLETE")


class YieldCoverageTests(unittest.TestCase):
    def test_no_feed_returns_explicit_missing_three_tenors(self):
        self.assertEqual([x.status for x in yield_feed_status(None, at=NOW)], ["MISSING"] * 3)

    def test_15m_reference_does_not_masquerade_as_1m_ticks(self):
        obs = [SimpleNamespace(name=tenor, provider="verified-test", value=4.0,
                               observed_at=NOW.isoformat(),
                               latest_observation_freshness="FRESH",
                               window_coverage={"15m": "VALID"})
               for tenor in ("US2Y", "US10Y", "US30Y")]
        snapshot = SimpleNamespace(observations=obs)
        self.assertEqual([x.status for x in yield_feed_status(snapshot, at=NOW)], ["15M_ONLY"] * 3)

    def test_historical_yield_snapshot_is_as_of_only_and_never_creates_schema(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.db"
            with self.assertRaises(LookupError):
                load_archived_yield_snapshot(at=NOW, path=path)
            with connect(path) as db:
                row = db.execute(
                    "SELECT name FROM sqlite_master WHERE name='cross_market_state_snapshots'"
                ).fetchone()
                self.assertIsNone(row)
                db.execute("CREATE TABLE cross_market_state_snapshots (as_of TEXT, payload_json TEXT)")
                for minute, name in ((-1, "past"), (1, "future")):
                    at = (NOW + timedelta(minutes=minute)).isoformat()
                    snapshot = CrossMarketStateSnapshot(name, "Tech100", at, (), {}, {})
                    db.execute("INSERT INTO cross_market_state_snapshots VALUES (?, ?)",
                               (at, json.dumps(snapshot.to_record())))
            loaded = load_archived_yield_snapshot(at=NOW, path=path)
            self.assertEqual(loaded.snapshot_id, "past")


class ArchiveNewsTests(unittest.TestCase):
    def test_read_only_archived_tech_and_macro_news_no_future_arrival(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "news.db"
            with connect(path) as db:
                db.executescript("""
                    CREATE TABLE telegram_raw_posts (
                        message_id TEXT PRIMARY KEY, channel TEXT NOT NULL,
                        published_at TEXT NOT NULL, first_seen_at TEXT NOT NULL,
                        payload_json TEXT NOT NULL
                    );
                """)
                rows = [
                    ("tech", "tech-source", "2026-11-20T13:55:00+00:00", "2026-11-20 13:56:00",
                     json.dumps({"message_text": "Nvidia data center earnings guidance"})),
                    ("macro", "macro-source", "2026-11-20T13:58:00+00:00", "2026-11-20 13:59:00",
                     json.dumps({"message_text": "Fed rate decision and CPI inflation"})),
                    ("future", "macro-source", "2026-11-20T13:58:00+00:00", "2026-11-20 14:01:00",
                     json.dumps({"message_text": "Treasury yield moves higher"})),
                ]
                for row in rows:
                    db.execute("INSERT INTO telegram_raw_posts VALUES (?, ?, ?, ?, ?)", row)
            with patch("tech100_synthesis_data_v1.connect", wraps=connect) as conn:
                read = load_archived_news(at=NOW, within=timedelta(minutes=10), path=path)
                self.assertEqual(conn.call_count, 1)
            self.assertEqual([item.story_id for item in read], ["tech", "macro"])
            self.assertIn(TECH_NEWS, read[0].topics)
            self.assertIn(MACRO_NEWS, read[1].topics)
            self.assertTrue(all(item.received_at <= NOW for item in read))

    def test_gdelt_archive_is_read_only_and_never_invents_missing_files(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "gdelt.db"
            with self.assertRaises(FileNotFoundError):
                load_archived_gdelt_news(at=NOW, database_path=path)
            self.assertFalse(path.exists())
            with sqlite3.connect(path) as db:
                db.execute("""CREATE TABLE gdelt_candidates (
                    event_id TEXT, provider TEXT, title TEXT,
                    published_at TEXT, retrieved_at TEXT
                )""")
                db.execute("INSERT INTO gdelt_candidates VALUES (?, ?, ?, ?, ?)",
                           ("1", "gdelt", "Nvidia chipmaker forecast",
                            "2026-11-20T13:56:00+00:00", "2026-11-20T13:58:00+00:00"))
                db.execute("INSERT INTO gdelt_candidates VALUES (?, ?, ?, ?, ?)",
                           ("2", "gdelt", "Fed rate decision",
                            "2026-11-20T13:56:00+00:00", "2026-11-20T14:01:00+00:00"))
            read = load_archived_gdelt_news(at=NOW, database_path=path)
            self.assertEqual(len(read), 1)
            self.assertEqual(read[0].topics, (TECH_NEWS,))
            self.assertTrue(read[0].story_id.startswith("gdelt:"))


if __name__ == "__main__":
    unittest.main()
