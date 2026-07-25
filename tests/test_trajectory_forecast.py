from __future__ import annotations

import unittest

import pandas as pd

from trajectory_forecast import build_trade_plan, build_trajectory, update_plan_status


class TrajectoryForecastTests(unittest.TestCase):
    def setUp(self) -> None:
        self.market = pd.DataFrame({"close": [100.0, 100.2, 100.1, 100.4, 100.5, 100.7]})

    def test_uncertainty_widens_with_time(self) -> None:
        points = build_trajectory(
            expected_move_pct=1.0,
            confidence_pct=70.0,
            volatility_pct=0.2,
        )
        widths = [point.upper_pct - point.lower_pct for point in points]
        self.assertGreater(widths[-1], widths[1])
        self.assertGreater(points[-1].expected_pct, points[1].expected_pct)

    def test_higher_confidence_reduces_cone_width(self) -> None:
        low = build_trajectory(expected_move_pct=1.0, confidence_pct=45.0, volatility_pct=0.2)
        high = build_trajectory(expected_move_pct=1.0, confidence_pct=90.0, volatility_pct=0.2)
        low_width = low[-1].upper_pct - low[-1].lower_pct
        high_width = high[-1].upper_pct - high[-1].lower_pct
        self.assertLess(high_width, low_width)

    def test_long_plan_has_ordered_levels(self) -> None:
        plan = build_trade_plan(
            instrument="Brent",
            market=self.market,
            direction="LONG",
            confidence_pct=75.0,
            expected_move_pct=1.2,
        )
        self.assertLess(plan.invalidation_price, plan.entry_low)
        self.assertLess(plan.entry_low, plan.entry_high)
        self.assertLess(plan.entry_high, plan.target_1)
        self.assertLess(plan.target_1, plan.target_2)
        self.assertEqual(update_plan_status(plan, plan.target_1), "TARGET_1_HIT")

    def test_short_plan_has_ordered_levels(self) -> None:
        plan = build_trade_plan(
            instrument="Silver",
            market=self.market,
            direction="SHORT",
            confidence_pct=75.0,
            expected_move_pct=1.2,
        )
        self.assertLess(plan.target_2, plan.target_1)
        self.assertLess(plan.target_1, plan.entry_low)
        self.assertLess(plan.entry_low, plan.entry_high)
        self.assertLess(plan.entry_high, plan.invalidation_price)
        self.assertEqual(update_plan_status(plan, plan.target_1), "TARGET_1_HIT")

    def test_weak_signal_returns_no_trade(self) -> None:
        plan = build_trade_plan(
            instrument="Gold",
            market=self.market,
            direction="LONG",
            confidence_pct=30.0,
            expected_move_pct=1.0,
        )
        self.assertEqual(plan.status, "NO_TRADE")
        self.assertIsNone(plan.entry_low)


if __name__ == "__main__":
    unittest.main()
