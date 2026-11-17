"""Synthetic oracle checks for read-only coupled-market research."""
from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from market_instrument_ensemble_v1 import (
    _predict_next_return,
    ensemble_report,
    exact_minute_returns,
    spectral_coherence,
)


def closes(returns: np.ndarray, *, name: str = "close") -> pd.Series:
    dates = pd.date_range("2026-10-19T00:00:00Z", periods=len(returns), freq="1min")
    return pd.Series(100 * np.exp(np.cumsum(returns)), index=dates, name=name)


class CoupledInstrumentTests(unittest.TestCase):
    def test_missing_minute_never_creates_a_gap_return(self):
        series = closes(np.full(300, 0.001))
        missing = series.drop(series.index[140])
        results = exact_minute_returns({"tech": series, "peer": missing})
        self.assertTrue(pd.isna(results.loc[series.index[140], "peer"]))
        self.assertTrue(pd.isna(results.loc[series.index[141], "peer"]))
        self.assertTrue(np.isfinite(results.loc[series.index[142], "peer"]))

    def test_known_one_minute_leader_predicts_next_minute_on_holdout(self):
        rng = np.random.default_rng(12)
        peer_ret = rng.normal(0, 0.001, 2400)
        tech_ret = np.zeros(2400)
        tech_ret[1:] = peer_ret[:-1] * 0.8 + rng.normal(0, 0.00015, 2399)
        minute = exact_minute_returns({"tech": closes(tech_ret), "peer": closes(peer_ret)})
        success = _predict_next_return(minute["peer"], minute["tech"], 1)
        self.assertGreater(success["test_r2"], 0.7)
        self.assertGreater(success["test_up_hit_pct"], 90)

    def test_unrelated_noise_has_no_holdout_predictive_power(self):
        rng = np.random.default_rng(5)
        prices = {"tech": closes(rng.normal(0, 0.001, 3000)),
                  "peer": closes(rng.normal(0, 0.001, 3000))}
        report = ensemble_report(prices, target="tech")
        self.assertLess(abs(report["couplings"][0]["Retningskorrelasjon"]), 0.1)
        self.assertLess(report["leads"][0]["Test R²"], 0.05)

    def test_identical_strings_are_coherent_and_common_factor_is_detected(self):
        rng = np.random.default_rng(123)
        common = rng.normal(0, 0.001, 2500)
        shared = closes(common)
        overlap = exact_minute_returns({"a": shared, "b": shared})
        coherent = spectral_coherence(overlap["a"], overlap["b"])
        self.assertGreater(coherent["windows"], 8)
        self.assertGreater(coherent["coherence"][16], 0.99)
        report = ensemble_report({"a": shared, "b": shared,
                                  "c": closes(common * 0.5)}, target="a")
        self.assertGreater(report["factor"]["explained_pct"], 99)
        self.assertEqual(report["factor"]["common_minutes"], 2499)

    def test_disjoint_sessions_do_not_invent_common_factor(self):
        rng = np.random.default_rng(66)
        a = closes(rng.normal(0, 0.001, 1200))
        b = a.copy()
        c = a.copy()
        b.index += pd.Timedelta(days=3)
        c.index += pd.Timedelta(days=6)
        report = ensemble_report({"a": a, "b": b, "c": c}, target="a")
        self.assertIsNone(report["factor"])
        self.assertEqual(report["couplings"][0]["Felles 1m"], 0)


if __name__ == "__main__":
    unittest.main()
