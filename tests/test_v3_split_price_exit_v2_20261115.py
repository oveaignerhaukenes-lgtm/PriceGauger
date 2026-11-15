"""V2 split-clock entry unchanged; adverse price confirms E2 warning."""
from __future__ import annotations

from datetime import datetime,timedelta,timezone
from tempfile import TemporaryDirectory
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import unittest

import autotrader_v3_macd_stoch_v21_split_v2 as v2
from autotrader_v3_domain import TargetInventoryV3
from autotrader_v3_macd_stoch_v2 import MacdStochV2DecisionV3
from autotrader_v3_registry_v1 import strategy_v3,live_config_issues_v3,sim_config_issues_v3
from autotrader_v3_strategy_registry_v1 import strategy_adapter_v3
from strategy_lab_v2_replay import PURE_V3

ZERO=datetime(2026,11,15,tzinfo=timezone.utc)


def source(side=1, adverse=False, shock=False):
    result=[]
    for i in range(40):
        # 14 stable prior bars: ATR approx 2, no self-inflating shock ATR.
        value=30000+side*i*.2
        if adverse and i>=37:
            value=30000+side*(37*.2-(i-36)*2.5)
        if shock and i==39:
            value=30000+side*(38*.2-12)
        op=value-side*.4
        hi=max(op,value)+1.
        lo=min(op,value)-1.
        result.append(SimpleNamespace(bar_time=ZERO+timedelta(minutes=i),
                                     open=op,high=hi,low=lo,close=value,volume=None))
    return tuple(result)


def observation():
    return SimpleNamespace(bar_time=ZERO+timedelta(minutes=40),
                           closed_at=ZERO+timedelta(minutes=40),spread=.4)


def base_decision(side,amount=None):
    return MacdStochV2DecisionV3(TargetInventoryV3(float(side*.01 if amount is None else amount)),
                                 "OPEN","V2.1",.4,.6,.7,.5)


def eval_v2(side=1,current=.01,adverse=False,shock=False,exit_against=True):
    config=lambda *_,**kw: side*.3 if kw["minutes"]==15 else (-side*.2 if exit_against else side*.2)
    with patch.object(v2,"_latest_macd",side_effect=config), patch.object(
            v2,"macd_stoch_v21_target_v3",return_value=base_decision(side,0.)):
        return v2.split_price_exit_v2(side=side,
            current_target=TargetInventoryV3(side*current),observation=observation(),
            source_bars=source(side,adverse,shock),bars=(),
            regime_timeframe_minutes=15,exit_timeframe_minutes=2,market_name="Tech100")


class SplitV2Test(unittest.TestCase):
    def test_price_rising_must_not_exit_because_macd_negative(self):
        for side in (1,-1):
            result=eval_v2(side)
            self.assertEqual(result.action,"HOLD_PRICE_UNCONFIRMED")
            self.assertAlmostEqual(result.target.amount,side*.01)

    def test_price_confirms_adverse_macd_exit_both_sides(self):
        for side in (1,-1):
            e=v2.price_exit_evidence_v2(source_bars=source(side,adverse=True),
                                      cutoff=observation().closed_at,
                                      market_name="Tech100",side=side)
            # Synthetic minute bodies are green in the chosen direction,
            # but closes fall across minutes: price, not candle color, matters.
            self.assertGreaterEqual(e.adverse_candles_3m,2)
            result=eval_v2(side,adverse=True)
            self.assertEqual(result.action,"PRICE_CONFIRMED_EXIT_FLAT")
            self.assertEqual(result.target.amount,0.)

    def test_violent_price_structure_break_exits_despite_positive_macd(self):
        for side in (1,-1):
            result=eval_v2(side,shock=True,exit_against=False)
            self.assertEqual(result.action,"PRICE_SHOCK_FLAT")

    def test_counter_macd_can_hold_but_must_not_build(self):
        with patch.object(v2,"_latest_macd",side_effect=lambda *_,**kw:
                          .3 if kw["minutes"]==15 else -.2), patch.object(
                          v2,"macd_stoch_v21_target_v3",return_value=base_decision(1,.02)):
            result=v2.long_flat_target_v2(current_target=TargetInventoryV3(.01),
                observation=observation(),source_bars=source(),market_name="Tech100")
        self.assertEqual(result.action,"WAIT_EXIT_MACD_FOR_BUILD")
        self.assertAlmostEqual(result.target.amount,.01)

    def test_incomplete_source_never_authorizes_entry(self):
        with patch.object(v2,"_latest_macd",return_value=.2):
            result=v2.long_flat_target_v2(current_target=TargetInventoryV3(0),
                observation=observation(),source_bars=source()[-9:])
        self.assertEqual(result.action,"CLOCK_OR_PRICE_UNAVAILABLE_FLAT")

    def test_price_context_does_not_look_ahead(self):
        data=source(adverse=True)
        cutoff=observation().closed_at
        a=v2.price_exit_evidence_v2(source_bars=data,cutoff=cutoff,market_name="Tech100",side=1)
        future=(SimpleNamespace(bar_time=cutoff+timedelta(minutes=1),open=30000,
                                high=99999,low=1,close=1,volume=None),)
        b=v2.price_exit_evidence_v2(source_bars=data+future,cutoff=cutoff,
                                    market_name="Tech100",side=1)
        self.assertEqual(a,b)

    def test_v2_are_independent_live_sim_and_paper_routes(self):
        self.assertTrue(v2.SPLIT_V2_KEYS_V3.isdisjoint(v2.SPLIT_KEYS_V3))
        for key in v2.SPLIT_V2_KEYS_V3:
            spec=strategy_v3(key)
            self.assertTrue(spec.runtime_ready)
            self.assertTrue(strategy_adapter_v3(spec.runtime_key).live_route_enabled)
            self.assertIn(key,PURE_V3)
            self.assertFalse(live_config_issues_v3(strategy_key=key,timeframe="1m",
                regime_timeframe="15m",exit_timeframe="2m",control_mode="Manuell",modifiers=()))
            self.assertFalse(sim_config_issues_v3(strategy_key=key,timeframe="1m",
                regime_timeframe="15m",exit_timeframe="2m",control_mode="Manuell",modifiers=()))

    def test_saxo_legal_minimum_tranche(self):
        try:
            from autotrader_v3_strategy_sizing_v1 import strategy_amount_config_v3
            from autotrader_open_sizing_v2 import EntryInstrumentRulesV2
        except ModuleNotFoundError:
            self.skipTest("Saxo HTTP client dependency missing from minimal local environment")
        rules=EntryInstrumentRulesV2(uic=4912,asset_type="CfdOnIndex",currency="USD",
            is_tradable=True,non_tradable_reason="None",amount_decimals=2,
            minimum_amount=.01,increment_size=.01,contract_size=1,
            supported_order_types=("Market",),amount_quantum=.01,
            reference_minimum_amount=.01,minimum_order_value=None)
        for key in v2.SPLIT_V2_KEYS_V3:
            self.assertEqual(strategy_amount_config_v3(strategy_key=key,rules=rules),
                             strategy_amount_config_v3(strategy_key="macd-stoch-v2-1",rules=rules))


if __name__=="__main__":unittest.main()
