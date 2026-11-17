"""Impulse Catcher v1.1: no false feed gaps caused by slow V3 evaluation."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import json
import unittest

from autotrader_v3_order_guard_v1 import ensure_schema as ensure_order_guard
from autotrader_v3_registry_v1 import live_config_issues_v3, strategy_v3
from autotrader_v3_tick_shadow_live_v1 import (
    IMPULSE_LONG_CATALOG_KEY, IMPULSE_SHORT_CATALOG_KEY,
    IMPULSE_LONG_V11_CATALOG_KEY, IMPULSE_SHORT_V11_CATALOG_KEY,
    TICK_CATALOG_KEYS, TICK_RUNTIME_KEYS, evaluate_tick_live_v3,
)
from database import connect
from live_sim_hyper_quotes_v1 import HyperQuoteRecorder


START = datetime(2026, 11, 17, 13, 0, tzinfo=timezone.utc)


def record(recorder, second, mid):
    at = START + timedelta(seconds=second)
    recorder.observe(
        SimpleNamespace(market="US Tech 100 NAS", uic=4912,
                        asset_type="CfdOnIndex", bid=mid - .75,
                        ask=mid + .75, observed_at=at),
        tradable=True, now=at,
    )


def evaluate(db, key, second, amount):
    return evaluate_tick_live_v3(
        trader_id="pilot", strategy_key=key, account_uic=4912,
        asset_type="CfdOnIndex", actual_amount=amount, tranche=.01,
        db_path=db, now=START + timedelta(seconds=second),
    ).decision


class ImpulseCatcherV11DataflowTest(unittest.TestCase):
    def test_v11_registered_but_independent_of_v1(self):
        for key, old in ((IMPULSE_LONG_V11_CATALOG_KEY, IMPULSE_LONG_CATALOG_KEY),
                         (IMPULSE_SHORT_V11_CATALOG_KEY, IMPULSE_SHORT_CATALOG_KEY)):
            self.assertNotEqual(key, old)
            self.assertIn(key, TICK_CATALOG_KEYS)
            spec = strategy_v3(key)
            self.assertIn(spec.runtime_key, TICK_RUNTIME_KEYS)
            self.assertFalse(live_config_issues_v3(strategy_key=key, timeframe="1m",
                                                    control_mode="Manuell", modifiers=()))

    def test_slow_worker_with_contiguous_real_quotes_is_not_feed_outage(self):
        for side, old, new, amount in (
            ("SHORT", IMPULSE_SHORT_CATALOG_KEY, IMPULSE_SHORT_V11_CATALOG_KEY, -.01),
            ("LONG", IMPULSE_LONG_CATALOG_KEY, IMPULSE_LONG_V11_CATALOG_KEY, .01),
        ):
            direction = -1 if side == "SHORT" else 1
            for key in (old, new):
                with self.subTest(side=side, version=key), TemporaryDirectory() as d:
                    db = str(Path(d) / "quotes.db")
                    recorder = HyperQuoteRecorder(db)
                    ensure_order_guard(db)
                    record(recorder, 0, 30000.)
                    self.assertEqual(evaluate(db, key, 0, amount).action, "BOOTSTRAP")
                    # The recorder remained healthy at 1Hz, but V3 evaluated
                    # nothing for 30 seconds (e.g. slow Saxo reconciliation).
                    for second in range(1, 31):
                        record(recorder, second, 30000. + direction * second)
                    result = evaluate(db, key, 30, amount)
                    if key == old:
                        self.assertEqual(result.action, "QUOTE_GAP_FLAT")
                        self.assertEqual(result.target.amount, 0.)
                    else:
                        self.assertEqual(result.action, "HOLD_" + side)
                        self.assertAlmostEqual(result.target.amount, amount)

    def test_tolerates_eight_second_silence_but_not_nine(self):
        for seconds, expected in ((8, "HOLD_SHORT"), (9, "QUOTE_GAP_FLAT")):
            with self.subTest(seconds=seconds), TemporaryDirectory() as d:
                db = str(Path(d) / "quotes.db")
                recorder = HyperQuoteRecorder(db)
                ensure_order_guard(db)
                record(recorder, 0, 30000.)
                evaluate(db, IMPULSE_SHORT_V11_CATALOG_KEY, 0, -.01)
                record(recorder, seconds, 30000.)
                result = evaluate(db, IMPULSE_SHORT_V11_CATALOG_KEY, seconds, -.01)
                self.assertEqual(result.action, expected)

    def test_gap_during_flat_cannot_create_jump_entry(self):
        with TemporaryDirectory() as d:
            db = str(Path(d) / "quotes.db")
            recorder = HyperQuoteRecorder(db)
            ensure_order_guard(db)
            record(recorder, 0, 30000.)
            evaluate(db, IMPULSE_SHORT_V11_CATALOG_KEY, 0, 0.)
            for second in range(1, 41):
                record(recorder, second, 30000. + (second % 2) * .1)
            evaluate(db, IMPULSE_SHORT_V11_CATALOG_KEY, 40, 0.)
            record(recorder, 48, 29975.)
            result = evaluate(db, IMPULSE_SHORT_V11_CATALOG_KEY, 48, 0.)
            self.assertEqual(result.target.amount, 0.)
            with connect(db) as conn:
                row = conn.execute("SELECT state_json FROM pg_v3_tick_live_state WHERE trader_id=?",
                                   ("pilot",)).fetchone()
            self.assertEqual(len(json.loads(row["state_json"])["samples"]), 1)

    def test_old_provider_quote_is_not_accepted_as_fresh(self):
        with TemporaryDirectory() as d:
            db = str(Path(d) / "quotes.db")
            recorder = HyperQuoteRecorder(db)
            ensure_order_guard(db)
            record(recorder, 0, 30000.)
            evaluate(db, IMPULSE_SHORT_V11_CATALOG_KEY, 0, -.01)
            stamp = START + timedelta(seconds=8)
            with connect(db) as conn:
                conn.execute("""INSERT INTO lsim_hyper_quotes_1s
                    (provider_uic,quote_at,market_name,asset_type,bid,ask,received_at)
                    VALUES(?,?,?,?,?,?,?)""", (4912, stamp.isoformat(), "Tech100",
                    "CfdOnIndex", 29999., 30001.,
                    (stamp + timedelta(seconds=8)).isoformat()))
            result = evaluate(db, IMPULSE_SHORT_V11_CATALOG_KEY, 8, -.01)
            self.assertEqual(result.action, "WAIT_BAD_BBO")
            self.assertEqual(result.target.amount, -.01)

    def test_engine_backlog_over_two_minutes_is_not_labeled_saxo_gap(self):
        with TemporaryDirectory() as d:
            db = str(Path(d) / "quotes.db")
            recorder = HyperQuoteRecorder(db)
            ensure_order_guard(db)
            record(recorder, 0, 30000.)
            evaluate(db, IMPULSE_SHORT_V11_CATALOG_KEY, 0, -.01)
            record(recorder, 121, 29995.)
            result = evaluate(db, IMPULSE_SHORT_V11_CATALOG_KEY, 121, -.01)
            self.assertEqual(result.action, "ENGINE_BACKLOG_FLAT")
            self.assertEqual(result.target.amount, 0.)


if __name__ == "__main__":
    unittest.main()
