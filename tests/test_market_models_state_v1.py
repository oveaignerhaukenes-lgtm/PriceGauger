"""Read-only, deterministic tests for the first Market Models foundation."""
from __future__ import annotations

from pathlib import Path
import unittest

import numpy as np
import pandas as pd

from market_models_state_v1 import (
    MARKET_MODEL_CATALOG_V1,
    RHYTHM_LABELS,
    TREND_LABELS,
    market_state_history_v1,
    quantize_market_state_v1,
)
from navigation_config import PAGE_GROUPS


def sample(returns: list[float] | np.ndarray, *, start: str = "2026-11-16T12:00:00Z") -> pd.Series:
    amounts = np.asarray(returns, dtype=float)
    values = 100 * np.exp(np.cumsum(np.concatenate(([0.0], amounts))))
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq="1min"))


class MarketStateV1Tests(unittest.TestCase):
    def test_rising_fast_and_flat_fast_are_distinct_states(self):
        rising = quantize_market_state_v1(sample([0.003, -0.001] * 30))
        sideways = quantize_market_state_v1(sample([0.002, -0.002] * 30))
        self.assertEqual(rising.state_key, "OPP/RASK")
        self.assertEqual(sideways.state_key, "SIDEVEIS/RASK")
        self.assertEqual(rising.rhythm_evidence, "MÅLT")
        self.assertAlmostEqual(rising.efficiency, 0.5, places=6)
        self.assertEqual(rising.median_run_minutes, 1.0)

    def test_down_medium_and_up_slow_use_the_same_market_independent_ranges(self):
        falling = quantize_market_state_v1(sample([-0.003] * 2 + [0.001] * 2 +
                                                     ([-0.003] * 2 + [0.001] * 2) * 14))
        rising = quantize_market_state_v1(sample(([0.003] * 5 + [-0.001] * 5) * 6))
        self.assertEqual(falling.state_key, "NED/MIDDELS")
        self.assertEqual(falling.median_run_minutes, 2.0)
        self.assertEqual(rising.state_key, "OPP/LANGSOM")
        self.assertEqual(rising.median_run_minutes, 5.0)

    def test_no_pseudo_states_across_gaps_or_completely_frozen_prices(self):
        prices = sample([0.001] * 60)
        gap = prices.drop(prices.index[20])
        self.assertIsNone(quantize_market_state_v1(gap))
        self.assertIsNone(quantize_market_state_v1(sample([0.0] * 60)))
        with self.assertRaises(ValueError):
            quantize_market_state_v1(prices.iloc[::-1])

    def test_unobserved_cycle_has_explicit_weak_evidence(self):
        monotone = quantize_market_state_v1(sample([0.001] * 60))
        self.assertEqual(monotone.trend, "OPP")
        self.assertEqual(monotone.rhythm, "LANGSOM")
        self.assertIsNone(monotone.median_run_minutes)
        self.assertEqual(monotone.rhythm_evidence, "SVAK / INGEN FULL SYKLUS")

    def test_hysteresis_reduces_threshold_flapping_without_future_data(self):
        first = quantize_market_state_v1(sample([0.003, -0.001] * 30,
                                                start="2026-11-16T11:55:00Z"))
        borderline = sample([0.002, -0.001077] * 30)
        default = quantize_market_state_v1(borderline)
        retained = quantize_market_state_v1(borderline, previous=first)
        self.assertEqual(default.trend, "SIDEVEIS")
        self.assertEqual(retained.trend, "OPP")
        with self.assertRaises(ValueError):
            quantize_market_state_v1(sample([0.003, -0.001] * 30), previous=retained)

    def test_history_is_as_of_causal_and_never_splices_sessions(self):
        first = sample([0.003, -0.001] * 90)
        later = sample([0.003, -0.001] * 95)
        later.iloc[-1] *= 1.4  # One unpredictable future impulse.
        original = market_state_history_v1(first)
        extended = market_state_history_v1(later)
        prefix = {state.as_of: state for state in extended}
        for state in original[:-1]:
            self.assertEqual(prefix[state.as_of], state)
            self.assertEqual(state.as_of, state.bar_at + pd.Timedelta(minutes=1))
        gap = pd.concat((first.iloc[:70], first.iloc[70:].rename(
            index=lambda stamp: stamp + pd.Timedelta(hours=8))))
        gaps = market_state_history_v1(gap)
        self.assertFalse(any(first.index[70] <= x.bar_at < first.index[70] + pd.Timedelta(hours=8)
                             for x in gaps))

    def test_catalog_is_extensible_and_presented_without_live_writes(self):
        self.assertEqual({spec.key for spec in MARKET_MODEL_CATALOG_V1},
                         {"coupled_strings_state_v1"})
        self.assertEqual(len(TREND_LABELS) * len(RHYTHM_LABELS), 9)
        matches = [page for pages in PAGE_GROUPS.values() for page in pages
                   if page["title"] == "Markedsmodeller"]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["url_path"], "Markedsmodeller")
        ui = Path("pages/0_Markedsmodeller.py").read_text(encoding="utf-8").lower()
        self.assertIn("canonicalmarketbarstorev2().load_instrument_range", ui)
        self.assertIn("list_subscribed_sources_v2", ui)
        for forbidden in ("place_order(", "set_live_enabled", "save_autotrader_config_v3",
                          "switch_live_strategy", "request_manual_target", "saxo_provider",
                          "insert into", "update autotrader_"):
            self.assertNotIn(forbidden, ui)


if __name__ == "__main__":
    unittest.main()
