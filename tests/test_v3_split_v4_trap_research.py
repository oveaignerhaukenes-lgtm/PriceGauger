"""Regression tests for the separate, PAPER-only V4 trap exit proposal."""
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from autotrader_v3_domain import TargetInventoryV3
from autotrader_v3_registry_v1 import STRATEGIES_V3
from autotrader_v3_macd_stoch_v21_split_v1 import _decision
from strategy_lab_v2_replay import (
    PURE_V3, REPLAY_SPLIT_KEYS, REPLAY_V4_KEYS, ReplayCostsV2,
    V4_LONG_TRAP_PAPER_KEY, V4_SHORT_TRAP_PAPER_KEY, strategy_catalog_v2,
    replay_v3_strategy_v2,
)
from autotrader_v3_split_v4_trap_research import (
    trap_profile_v4, split_trap_exit_research_v4,
)


class TestTrapResearch(unittest.TestCase):
    def setUp(self):
        self.start = datetime(2026, 11, 18, 12, tzinfo=timezone.utc)

    def bars(self, increments):
        price = 27000.
        result = []
        for i, change in enumerate(increments):
            before = price
            price += change
            result.append(SimpleNamespace(
                bar_time=self.start + timedelta(minutes=i),
                open=before, high=max(before, price)+.5,
                low=min(before, price)-.5, close=price, volume=None))
        return result

    def obs(self, bars):
        return SimpleNamespace(bar_time=bars[-1].bar_time,
                               closed_at=bars[-1].bar_time+timedelta(minutes=1),
                               spread=1.)

    def recurring(self):
        # Repeated shallow, two-minute countertrend legs, with net uptrend.
        return self.bars(([5., 5., -2., -2., 4., 4.] * 10) + [-2., -2.])

    def test_completed_traps_identified_without_future(self):
        bars = self.recurring()
        cutoff = self.obs(bars).closed_at
        p = trap_profile_v4(source_bars=bars, cutoff=cutoff,
                            market_name='Tech100', side=1)
        self.assertIsNotNone(p)
        self.assertTrue(p.repeatable)
        self.assertEqual(2, p.active_minutes)
        self.assertGreaterEqual(p.prior_count, 2)
        future = self.bars([1000.])[-1]
        future.bar_time = bars[-1].bar_time + timedelta(minutes=2)
        self.assertEqual(p, trap_profile_v4(
            source_bars=bars + [future],
            cutoff=cutoff, market_name='Tech100', side=1))

    def test_soft_exit_can_hold_but_hard_exit_not_overridden(self):
        bars = self.recurring()
        def stub(*, observation, **_):
            return _decision(amount=0, action='PRICE_CONFIRMED_EXIT_FLAT',
                             reason='Exit MACD crossed', observation=observation)
        with patch('autotrader_v3_split_v4_trap_research.split_price_hist_regime_v3',
                   side_effect=stub):
            held = split_trap_exit_research_v4(
                side=1, current_target=TargetInventoryV3(.01),
                observation=self.obs(bars), source_bars=bars,
                market_name='Tech100')
            self.assertEqual('V4_REPEATED_TRAP_HOLD', held.action)
            self.assertEqual(.01, held.target.amount)

            flat = split_trap_exit_research_v4(
                side=1, current_target=TargetInventoryV3(0),
                observation=self.obs(bars), source_bars=bars,
                market_name='Tech100')
            self.assertEqual('PRICE_CONFIRMED_EXIT_FLAT', flat.action)

            with patch('autotrader_v3_split_v4_trap_research.split_price_hist_regime_v3',
                       return_value=_decision(amount=0, action='PRICE_SHOCK_FLAT',
                                              reason='Shock', observation=self.obs(bars))):
                protected = split_trap_exit_research_v4(
                    side=1, current_target=TargetInventoryV3(.01),
                    observation=self.obs(bars), source_bars=bars,
                    market_name='Tech100')
                self.assertEqual('PRICE_SHOCK_FLAT', protected.action)

    def test_missing_minute_and_unrecovered_trap_not_granted(self):
        bars = self.recurring()
        bars[-10].bar_time += timedelta(seconds=4)
        self.assertIsNone(trap_profile_v4(source_bars=bars,
                           cutoff=self.obs(bars).closed_at,
                           market_name='Tech100', side=1))

    def test_partial_rebound_is_not_counted_as_recovered_trap(self):
        # One still-unrecovered 48-minute fall with 1-minute up-ticks does
        # not manufacture a sequence of completed dips.
        increments = [5.] * 12 + [-5., +1.] * 24 + [-2., -2.]
        bars = self.bars(increments)
        p = trap_profile_v4(source_bars=bars, cutoff=self.obs(bars).closed_at,
                            market_name='Tech100', side=1)
        self.assertIsNotNone(p)
        self.assertEqual(0, p.prior_count)
        self.assertFalse(p.within_tolerance)

    def test_paper_keys_cannot_be_armed_in_live_v3(self):
        self.assertEqual(REPLAY_V4_KEYS,
                         {V4_LONG_TRAP_PAPER_KEY, V4_SHORT_TRAP_PAPER_KEY})
        self.assertTrue(REPLAY_V4_KEYS.issubset(PURE_V3))
        self.assertTrue(REPLAY_V4_KEYS.issubset(REPLAY_SPLIT_KEYS))
        self.assertTrue(REPLAY_V4_KEYS.isdisjoint({s.key for s in STRATEGIES_V3}))
        catalog = strategy_catalog_v2()["V4 · Gjentatte traps · kun PAPER"]
        self.assertEqual(REPLAY_V4_KEYS, {s['key'] for s in catalog})
        self.assertTrue(all(s['replay_ready'] and not s['runtime_ready']
                            for s in catalog))

    def test_paper_replay_uses_real_v4_route(self):
        bars = self.bars(([4., -1., 3., -2.] * 65))
        for bar in bars:
            bar.market_name = 'Tech100'
        replay = replay_v3_strategy_v2(
            strategy_key=V4_LONG_TRAP_PAPER_KEY, bars=bars,
            costs=ReplayCostsV2(point_value_nok=10., spread_bps=4.,
                                variable_fee_bps=0., fixed_fee_nok=0.),
            timeframe='1m', regime_timeframe='5m', exit_timeframe='2m')
        self.assertGreater(len(replay.points), 0)


if __name__ == '__main__':
    unittest.main()
