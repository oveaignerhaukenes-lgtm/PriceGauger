"""Causal, entry-only safety rules for adaptive V5 PAPER prototype."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from autotrader_v3_domain import TargetInventoryV3
from autotrader_v3_registry_v1 import STRATEGIES_V3
from autotrader_v3_macd_stoch_v21_split_v1 import _decision
from autotrader_v3_split_v5_adaptive_research import (
    AdaptiveV5Paper, V5Policy, quantized_state_v5,
)


START = datetime(2026, 11, 16, tzinfo=timezone.utc)
MARKET = "Saxo US Tech 100"


def mock_bars(n=60, *, trend=.6):
    return tuple(SimpleNamespace(
        market_name=MARKET, market=MARKET,
        bar_time=START+timedelta(minutes=i),
        open=1000+i*trend-.1, high=1001+i*trend,
        low=999+i*trend, close=1000+i*trend,
        volume=1,
    ) for i in range(n))


def observation(index):
    stamp=START+timedelta(minutes=index+1)
    return SimpleNamespace(bar_time=stamp-timedelta(minutes=1),
                           closed_at=stamp, spread=1.)


class TestV5AdaptivePaper(unittest.TestCase):
    def test_v5_does_not_enter_live_registry(self):
        self.assertFalse(any("v5" in item.key for item in STRATEGIES_V3))

    def test_only_completed_history_no_future_lookahead(self):
        bars=mock_bars(60)
        policy=V5Policy()
        cutoff=START+timedelta(minutes=40)
        a=quantized_state_v5(
            source_bars=bars[:40], cutoff=cutoff, market_name=MARKET,
            side=1, losses_recent=2, trades_recent=3, policy=policy)
        b=quantized_state_v5(
            source_bars=bars[:40]+mock_bars(60,trend=-2.)[40:],
            cutoff=cutoff, market_name=MARKET,
            side=1, losses_recent=2, trades_recent=3, policy=policy)
        self.assertEqual(a,b)
        self.assertEqual(a.mode,"loss_defensive")
        self.assertEqual(a.required_efficiency,.48)

    def test_countertrend_price_fails_quantized_entry(self):
        bars=mock_bars(45,trend=-.7)
        policy=V5Policy()
        state=quantized_state_v5(source_bars=bars, cutoff=START+timedelta(minutes=45),
                                 market_name=MARKET,side=1,
                                 losses_recent=0,trades_recent=0,policy=policy)
        self.assertLess(state.momentum_atr, 0)
        self.assertLess(state.momentum_atr,state.required_momentum_atr)
        reverse=quantized_state_v5(source_bars=bars, cutoff=START+timedelta(minutes=45),
                                   market_name=MARKET,side=-1,
                                   losses_recent=0,trades_recent=0,policy=policy)
        self.assertGreater(reverse.momentum_atr,0)

    def test_loss_memory_changes_threshold_and_fades(self):
        policy=V5Policy(loss_memory_minutes=2, base_efficiency=0,
                        base_momentum_atr=0, after_one_loss_efficiency=.3,
                        after_one_loss_momentum_atr=0,
                        after_two_losses_efficiency=.7,
                        after_two_losses_momentum_atr=10)
        next_target=[.01]
        def underlying(*,current_target,observation,**kwargs):
            return _decision(amount=next_target[0], action="PROPOSE", reason="TEST",
                             observation=observation)
        model=AdaptiveV5Paper(side=1,policy=policy,base_strategy=underlying)
        bars=list(mock_bars(50,trend=.3))
        # Two completed round-trips: use real next-open samples, charge roundtrip spread
        # which exceeds the tiny positive gross move.
        for ix,current,proposal in ((20,0.,.01), (21,.01,0.), (22,0.,.01),
                                    (23,.01,0.), (24,0.,.01)):
            next_target[0]=proposal
            result=model(current_target=TargetInventoryV3(current),
                         observation=observation(ix), source_bars=bars[:ix+1],
                         market_name=MARKET)
        self.assertEqual(model.paper_round_trips,2)
        self.assertEqual(model.states[-1][1].losses_recent,2)
        self.assertEqual(model.states[-1][1].required_efficiency,.7)
        self.assertEqual(result.action,"V5_QUANTIZED_ENTRY_GUARD")
        self.assertEqual(result.target.amount,0.)

        # An unconditional flat from V3 may never be overridden by entry guard.
        next_target[0]=0.
        held=model(current_target=TargetInventoryV3(.01),
                   observation=observation(25), source_bars=bars[:26],
                   market_name=MARKET)
        self.assertEqual(held.target.amount,0.)
        self.assertEqual(held.action,"PROPOSE")
        for ix in (26,27,28,29):
            model(current_target=TargetInventoryV3(0),
                  observation=observation(ix),source_bars=bars[:ix+1],
                  market_name=MARKET)
        self.assertEqual(model.states[-1][1].losses_recent,0)

    def test_no_out_of_order_and_no_cross_gap_memory(self):
        bars=mock_bars(50)
        model=AdaptiveV5Paper(side=-1,base_strategy=lambda **kw: _decision(
            amount=0.,action="FLAT",reason="test",observation=kw["observation"]))
        for i in (20,21):
            model(current_target=TargetInventoryV3(0),observation=observation(i),
                  source_bars=bars[:i+1],market_name=MARKET)
        with self.assertRaises(ValueError):
            model(current_target=TargetInventoryV3(0),observation=observation(21),
                  source_bars=bars[:22],market_name=MARKET)
        model(current_target=TargetInventoryV3(0),observation=observation(24),
              source_bars=bars[:25],market_name=MARKET)
        self.assertEqual(len(model._realized),0)


if __name__ == "__main__":
    unittest.main()
