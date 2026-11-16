"""Read-only, causal historical research regressions; no database/Saxo required."""
import unittest
from datetime import datetime, timedelta, timezone

from market_rhythm_research_v1 import (
    aggregate_bars, clean_bars, confirmed_pivots, rhythm_prediction_report,
    structure_report,
)


def sample(prices, *, gaps=()):
    now = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)
    return clean_bars([
        {"bar_time": now + timedelta(minutes=i), "open": x, "high": x,
         "low": x, "close": x}
        for i, x in enumerate(prices) if i not in gaps
    ])


class ResearchTests(unittest.TestCase):
    def test_bucket_requires_every_minute(self):
        bars = sample([100, 101, 102, 103, 104, 105], gaps=(2,))
        buckets = aggregate_bars(bars, 2)
        self.assertEqual([x.at.minute for x in buckets], [0, 4])
        self.assertEqual(buckets[0].close, 101)
        self.assertEqual(buckets[-1].close, 105)

    def test_hh_hl_lh_ll_classify_only_on_confirmation(self):
        bars = sample([100, 110, 105, 120, 110, 115, 100, 108, 95, 105])
        turns = confirmed_pivots(bars, minutes=1, reversal_pct=3)
        labels = [x.label for x in turns]
        self.assertIn("HH", labels)
        self.assertIn("HL", labels)
        self.assertIn("LH", labels)
        self.assertIn("LL", labels)
        self.assertTrue(all(x.confirmed_at >= x.at for x in turns))
        self.assertTrue(any(x.confirmed_at > x.at for x in turns))

    def test_wick_extreme_never_confirms_on_same_intrabar_ambiguity(self):
        now = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)
        bars = clean_bars([
            {"bar_time": now + timedelta(minutes=i), "open": o, "high": h,
             "low": l, "close": c}
            for i, (o, h, l, c) in enumerate([
                (100, 100, 100, 100), (100, 110, 100, 108),
                (108, 112, 104, 105), (105, 106, 101, 103),
            ])
        ])
        turns = confirmed_pivots(bars, minutes=1, reversal_pct=5)
        peaks = [x for x in turns if x.kind == "PEAK"]
        self.assertEqual(len(peaks), 1)
        self.assertEqual(peaks[0].price, 112)
        self.assertEqual(peaks[0].at, now + timedelta(minutes=2))
        self.assertEqual(peaks[0].confirmed_at, now + timedelta(minutes=4))

    def test_gap_breaks_turns_and_future_outcomes(self):
        bars = sample([100, 110, 104, 115, 105, 120, 107, 112,
                       99, 110, 103, 115, 107, 119], gaps=(8,))
        turns = confirmed_pivots(bars, minutes=1, reversal_pct=2)
        segments = set(x.segment for x in turns)
        self.assertGreaterEqual(len(segments), 2)
        report = structure_report(bars, minutes=1, reversal_pct=2, min_cases=1)
        self.assertEqual(report["bars"], len(bars))
        self.assertTrue(all(row["N 30m"] == 0 for row in report["patterns"]))

    def test_invalid_or_duplicate_ohlc_rejected(self):
        with self.assertRaises(ValueError):
            clean_bars([{"bar_time": "2026-11-01T00:00:00Z",
                         "open": 100, "high": 99, "low": 98, "close": 100}])
        with self.assertRaises(ValueError):
            clean_bars([{"bar_time": "2026-11-01T00:00:00Z",
                         "open": 100, "high": 100, "low": 100, "close": 100}] * 2)

    def test_expanding_folds_do_not_claim_an_edge_without_samples(self):
        self.assertEqual(rhythm_prediction_report(sample([100, 101] * 10)), [])
        prices = [100.0]
        for i in range(500):
            prices.append(prices[-1] * (1.0002 if i % 2 else .9998))
        result = rhythm_prediction_report(sample(prices))
        self.assertEqual(len(result), 3)
        for row in result:
            self.assertGreater(row["Testpunkter"], 100)
            for model in ("Nullmodell", "Speilsymmetrisk", "Retningsspesifikk"):
                self.assertGreaterEqual(row[f"{model} treff %"], 0)
                self.assertLessEqual(row[f"{model} treff %"], 100)
                self.assertGreaterEqual(row[f"{model} Brier"], 0)

    def test_gapped_test_set_does_not_bridge_market_close(self):
        prices = [100 * (1.0002 ** i) for i in range(250)]
        bars = sample(prices, gaps=range(50, 100))
        report = rhythm_prediction_report(bars)
        self.assertEqual(len(report), 3)
        self.assertTrue(all(x["Testpunkter"] < len(bars) // 2 for x in report))


if __name__ == "__main__":
    unittest.main()
