"""Pre-cross R histogram must never act without observed, completed prices."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
import unittest

import autotrader_v3_macd_stoch_v21_split_v3 as v3
from autotrader_v3_domain import TargetInventoryV3
from autotrader_v3_macd_stoch_v2 import MacdStochV2DecisionV3
from autotrader_v3_registry_v1 import strategy_v3, live_config_issues_v3, sim_config_issues_v3
from autotrader_v3_strategy_registry_v1 import strategy_adapter_v3
from autotrader_v3_strategy_registry_v1 import evaluate_strategy_bar_v3
from autotrader_v3_macd_trailing_v1 import MacdTrailingConfigV3
from strategy_lab_v2_replay import PURE_V3

ZERO = datetime(2026, 11, 16, tzinfo=timezone.utc)


def observation():
    return SimpleNamespace(bar_time=ZERO + timedelta(minutes=40),
                           closed_at=ZERO + timedelta(minutes=40), spread=.2)


def decision(side, target=None):
    amount = side * .01 if target is None else target
    return MacdStochV2DecisionV3(TargetInventoryV3(amount),
                                 "OPEN", "V2.1", .2, .6, .7, .5)


def run_target(*, side=1, current=0., native=True, recovery=False,
               weakening=False, rollover=False, adverse_retrace=False,
               price_aligned=True, breakout=False,
               opposite_breakout=False, e2_agrees=True, base_target=None,
               source_available=True):
    regime = v3.RegimeHistogramV3(.4 if native else -.4,
                                   recovery, weakening, rollover) if source_available else None
    price = v3.PriceConfirmationV3(
        atr_points=3, signed_5m=5 if price_aligned else 0,
        signed_2m=2 if price_aligned else 0,
        aligned=price_aligned, strong_breakout=breakout,
        opposite_breakout=opposite_breakout,
    ) if source_available else None
    adverse = SimpleNamespace(severe_adverse_bar=False, structure_broken=False,
                              sustained_adverse=adverse_retrace,
                              signed_2m_change=-3 if adverse_retrace else 0,
                              atr_points=3) if source_available else None
    with (patch.object(v3, "regime_histogram_v3", return_value=regime),
          patch.object(v3, "price_confirmation_v3", return_value=price),
          patch.object(v3, "price_exit_evidence_v2", return_value=adverse),
          patch.object(v3, "_latest_macd", return_value=side * (1 if e2_agrees else -1)),
          patch.object(v3, "macd_stoch_v21_target_v3",
                       return_value=decision(side, base_target))):
        return v3.split_price_hist_regime_v3(
            side=side, current_target=TargetInventoryV3(side * current),
            observation=observation(), source_bars=(), market_name="Tech100")


def source_bars(count=400, *, side=1, breakout=False):
    rows = []
    for index in range(count):
        last = index >= count - 5
        close = 25000 + side * (index * .01 + (index - (count - 5)) * 5 if breakout and last else index * .01)
        rows.append(SimpleNamespace(
            bar_time=ZERO + timedelta(minutes=index),
            open=close - side * .2, high=close + 1., low=close - 1., close=close,
            volume=None))
    return tuple(rows)


class HistogramPriceSplitTest(unittest.TestCase):
    def test_pre_cross_cannot_open_on_histogram_without_price(self):
        for side in (1, -1):
            result = run_target(side=side, native=False, recovery=True, price_aligned=False)
            self.assertEqual(result.action, "REGIME_FLAT")
            self.assertEqual(result.target.amount, 0)

    def test_pre_cross_hist_and_breakout_can_open_both_sides(self):
        for side in (1, -1):
            result = run_target(side=side, native=False, recovery=True, breakout=True)
            self.assertEqual(result.action, "EARLY_HISTOGRAM_PRICE_OPEN")
            self.assertAlmostEqual(result.target.amount, side * .01)

    def test_early_reversal_closes_before_histogram_cross(self):
        for side in (1, -1):
            result = run_target(side=side, current=.01, native=True,
                                weakening=True, opposite_breakout=True)
            self.assertEqual(result.action, "EARLY_REGIME_REVERSAL_FLAT")
            self.assertEqual(result.target.amount, 0.)

    def test_no_exit_on_histogram_weakening_without_price_break(self):
        result = run_target(current=.01, weakening=True, opposite_breakout=False,
                            base_target=0.)
        self.assertEqual(result.action, "HOLD_PRICE_UNCONFIRMED")
        self.assertEqual(result.target.amount, .01)

    def test_first_histogram_rollover_plus_adverse_prices_protects_exposure(self):
        for side in (1, -1):
            result = run_target(side=side, current=.01, rollover=True,
                                adverse_retrace=True)
            self.assertEqual(result.action, "HISTOGRAM_EXHAUSTION_FLAT")
            self.assertEqual(result.target.amount, 0.)

    def test_histogram_rollover_without_actual_price_retrace_does_not_exit(self):
        result = run_target(current=.01, rollover=True, adverse_retrace=False,
                            base_target=0.)
        self.assertEqual(result.action, "HOLD_PRICE_UNCONFIRMED")
        self.assertEqual(result.target.amount, .01)

    def test_histogram_rollover_can_never_create_an_open(self):
        result = run_target(current=0., rollover=True, adverse_retrace=True)
        self.assertNotEqual(result.action, "HISTOGRAM_EXHAUSTION_FLAT")
        self.assertEqual(result.target.amount, .01)

    def test_price_can_override_E2_only_on_initial_open(self):
        allowed = run_target(e2_agrees=False, breakout=True)
        self.assertEqual(allowed.action, "OPEN_PRICE_OVERRIDE")
        blocked = run_target(e2_agrees=False, breakout=False)
        self.assertEqual(blocked.action, "WAIT_EXIT_MACD")
        build = run_target(current=.01, e2_agrees=False, breakout=True,
                           base_target=.02)
        self.assertEqual(build.action, "WAIT_EXIT_MACD")
        self.assertEqual(build.target.amount, .01)

    def test_confirmed_macd_needs_favorable_price_for_entry(self):
        result = run_target(price_aligned=False)
        self.assertEqual(result.action, "WAIT_PRICE_CONFIRMATION")

    def test_early_position_survives_small_price_pause(self):
        result = run_target(current=.01, native=False, recovery=True,
                            price_aligned=False, base_target=0.)
        self.assertEqual(result.action, "HOLD_PRICE_UNCONFIRMED")
        self.assertEqual(result.target.amount, .01)

    def test_gap_or_missing_regime_fails_flat(self):
        result = run_target(source_available=False)
        self.assertEqual(result.action, "CLOCK_OR_PRICE_UNAVAILABLE_FLAT")

    def test_three_closed_regime_candles_converge_but_do_not_cross(self):
        candles = source_bars(400)
        cutoff = ZERO + timedelta(minutes=400)
        def fake_macd(*_, **__):
            return tuple(SimpleNamespace(spread=spread,
                closed_at=ZERO + timedelta(minutes=close_min))
                for spread, close_min in ((-10, 380), (-7, 390), (-5, 400)))
        with patch.object(v3, "macd_observations_v2", side_effect=fake_macd):
            outcome = v3.regime_histogram_v3(
                source_bars=candles, cutoff=cutoff, minutes=10,
                market_name="Tech100", side=1)
        self.assertTrue(outcome.recovering_before_cross)
        self.assertFalse(outcome.weakening_before_cross)
        self.assertEqual(outcome.signed_spread, -5)

    def test_first_rollover_detected_while_macd_still_positive(self):
        candles = source_bars(400)
        cutoff = ZERO + timedelta(minutes=400)
        with patch.object(v3, "macd_observations_v2", return_value=tuple(
                SimpleNamespace(spread=spread,closed_at=ZERO+timedelta(minutes=t))
                for spread,t in ((4,380),(10,390),(6,400)))):
            result = v3.regime_histogram_v3(
                source_bars=candles,cutoff=cutoff,minutes=10,
                market_name="Tech100",side=1)
        self.assertTrue(result.rolling_over_from_peak)
        self.assertGreater(result.signed_spread, 0)

    def test_last_unclosed_regime_bar_cannot_change_signal(self):
        rows = source_bars(400)
        unfinished = source_bars(405)[400:]
        cutoff = ZERO + timedelta(minutes=400)
        def fake_macd(*_, **__):
            return tuple(SimpleNamespace(spread=x,
                closed_at=ZERO + timedelta(minutes=t))
                for x, t in ((-10, 380), (-7, 390), (-5, 400)))
        with patch.object(v3, "macd_observations_v2", side_effect=fake_macd):
            a = v3.regime_histogram_v3(source_bars=rows, cutoff=cutoff,
                minutes=10, market_name="Tech100", side=1)
            b = v3.regime_histogram_v3(source_bars=rows + unfinished, cutoff=cutoff,
                minutes=10, market_name="Tech100", side=1)
        self.assertEqual(a, b)

    def test_price_breakout_uses_only_closed_1m_data(self):
        rows = source_bars(40, breakout=True)
        cutoff = ZERO + timedelta(minutes=40)
        a = v3.price_confirmation_v3(source_bars=rows, cutoff=cutoff,
                                      market_name="Tech100", side=1)
        future = SimpleNamespace(bar_time=cutoff, open=1., high=1e8,
                                 low=.01, close=.01, volume=None)
        b = v3.price_confirmation_v3(source_bars=rows + (future,), cutoff=cutoff,
                                      market_name="Tech100", side=1)
        self.assertTrue(a.strong_breakout)
        self.assertEqual(a, b)

    def test_v3_is_separate_registered_sim_and_live_route(self):
        self.assertTrue(v3.SPLIT_V3_KEYS_V3.isdisjoint(v3.PREVIOUS_SPLIT_KEYS_V3))
        for key in v3.SPLIT_V3_KEYS_V3:
            self.assertTrue(strategy_v3(key).runtime_ready)
            self.assertTrue(strategy_adapter_v3(key).live_route_enabled)
            self.assertIn(key, PURE_V3)
            self.assertFalse(live_config_issues_v3(
                strategy_key=key, timeframe="1m", regime_timeframe="10m",
                exit_timeframe="2m", control_mode="Manuell", modifiers=()))
            self.assertFalse(sim_config_issues_v3(
                strategy_key=key, timeframe="1m", regime_timeframe="10m",
                exit_timeframe="2m", control_mode="Manuell", modifiers=()))

    def test_real_closed_bar_driver_dispatch_is_idempotent(self):
        with TemporaryDirectory() as temp:
            db_path = str(Path(temp) / "pilot.sqlite")
            regime = v3.RegimeHistogramV3(.4, False, False)
            price = v3.PriceConfirmationV3(3, 5, 2, True, True, False)
            adverse = SimpleNamespace(severe_adverse_bar=False,
                                      structure_broken=False, sustained_adverse=False)
            with (patch.object(v3, "regime_histogram_v3", return_value=regime),
                  patch.object(v3, "price_confirmation_v3", return_value=price),
                  patch.object(v3, "price_exit_evidence_v2", return_value=adverse),
                  patch.object(v3, "_latest_macd", return_value=.1),
                  patch.object(v3, "macd_stoch_v21_target_v3",
                               return_value=decision(1))):
                args = dict(strategy_key=v3.LONG_KEY_V3_PRICE_HIST,
                    trader_id="sim:histogram-v3:test", observation=observation(),
                    source_bars=(), bars=(), regime_timeframe_minutes=10,
                    exit_timeframe_minutes=2, market_name="Tech100",
                    config=MacdTrailingConfigV3(), db_path=db_path)
                first = evaluate_strategy_bar_v3(**args)
                duplicate = evaluate_strategy_bar_v3(**args)
            self.assertTrue(first.is_new)
            self.assertEqual(first.decision.target.amount, .01)
            self.assertFalse(duplicate.is_new)
            self.assertEqual(duplicate.decision.target.amount, .01)


if __name__ == "__main__":
    unittest.main()
