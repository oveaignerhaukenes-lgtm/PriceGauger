"""One-sided genuine 1s BBO impulse LIVE/PAPER contract.

Runs under pytest and also `python tests/test_v3_impulse_catcher_paired_20261115.py`
when pytest is unavailable locally.
"""
from __future__ import annotations

from datetime import datetime,timedelta,timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from autotrader_impulse_catcher_v1 import ImpulseCatcher,ImpulseCatcherConfig
from autotrader_impulse_catcher_replay_v1 import (
    ImpulseQuote,prepare_impulse_quotes,replay_impulse_catcher,
)
from autotrader_v3_tick_shadow_live_v1 import (
    IMPULSE_LONG_CATALOG_KEY,IMPULSE_SHORT_CATALOG_KEY,
    TICK_CATALOG_KEYS,TICK_RUNTIME_KEYS,evaluate_tick_live_v3,
)
from autotrader_v3_registry_v1 import (
    live_config_issues_v3,sim_config_issues_v3,strategy_v3,
)
from autotrader_v3_strategy_registry_v1 import strategy_adapter_v3
from autotrader_v3_order_guard_v1 import ensure_schema as ensure_order_guard
from live_sim_hyper_quotes_v1 import HyperQuoteRecorder
from database import connect


START=datetime(2026,11,15,13,0,tzinfo=timezone.utc)


def calm_and_impulse(side:str):
    s=1 if side=="LONG" else -1
    series=[]
    for tick in range(95):
        mid=30000+(tick%3)*.5
        if 61<=tick<=70:
            mid=30000+s*(tick-59)*6
        if 71<=tick<=74:
            mid=30000+s*(11*6-(tick-70)*8)
        if tick>=75:
            mid=30000+s*(11*6-4*8)
        series.append((START+timedelta(seconds=tick),mid))
    return series


class ImpulseCatcherTest(unittest.TestCase):
    def test_both_directions_trigger_fast_and_exit_fast(self):
        for side in ("LONG","SHORT"):
            model=ImpulseCatcher(ImpulseCatcherConfig(side=side))
            decisions=[]
            for at,mid in calm_and_impulse(side):
                d=model.on_quote(at,mid-.5,mid+.5)
                if d is not None:
                    decisions.append(d)
            self.assertTrue(any(d.target==side and d.window_seconds==3 for d in decisions))
            exits=[d for d in decisions if d.target=="FLAT"]
            self.assertTrue(exits)
            self.assertLessEqual((exits[0].at-START).total_seconds(),74)
            self.assertTrue(all(d.target in (side,"FLAT") for d in decisions))

    def test_no_wrong_side_or_stale_bbo_and_gap_flat(self):
        model=ImpulseCatcher(ImpulseCatcherConfig(side="LONG"))
        with self.assertRaises(ValueError):
            model.on_quote(START,0,1)
        with self.assertRaises(ValueError):
            model.on_quote(START,30001,30000)
        model.target="LONG"
        model.on_quote(START,30000,30001)
        action=model.on_quote(START+timedelta(seconds=10),30000,30001)
        self.assertEqual(action.reason,"QUOTE_GAP_FLAT")
        self.assertEqual(model.target,"FLAT")
        self.assertIsNone(model.on_quote(START+timedelta(seconds=10),30000,30001))

    def test_next_quote_bid_ask_paper_never_fills_on_signal_tick(self):
        series=calm_and_impulse("LONG")
        quotes=tuple(ImpulseQuote(t,p-.5,p+.5) for t,p in series)
        result=replay_impulse_catcher(quotes,ImpulseCatcherConfig(side="LONG"))
        self.assertGreaterEqual(result.signals,1)
        self.assertGreaterEqual(len(result.trades),1)
        first=result.trades[0]
        self.assertGreater(first.filled_at,first.signal_at)
        self.assertGreater(first.exited_at,first.exit_signal_at)
        self.assertAlmostEqual(first.fill_price, next(q.ask for q in quotes
                                                    if q.at==first.filled_at))
        self.assertAlmostEqual(first.exit_price, next(q.bid for q in quotes
                                                    if q.at==first.exited_at))
        self.assertAlmostEqual(first.gross_points,first.exit_price-first.fill_price)

    def test_bbo_validation_rejects_delayed_feed(self):
        rows=[dict(quote_at=START.isoformat(),received_at=START.isoformat(),
                   bid=29999.,ask=30001.),
              dict(quote_at=(START+timedelta(seconds=1)).isoformat(),
                   received_at=(START+timedelta(seconds=13)).isoformat(),
                   bid=29999.,ask=30001.)]
        self.assertEqual(len(prepare_impulse_quotes(rows)),1)

    def test_live_catalog_has_no_1m_sim_no_secret_broker_calls(self):
        for key,expected in ((IMPULSE_LONG_CATALOG_KEY,"LONG"),
                             (IMPULSE_SHORT_CATALOG_KEY,"SHORT")):
            self.assertIn(key,TICK_CATALOG_KEYS)
            spec=strategy_v3(key)
            self.assertTrue(spec.runtime_ready)
            self.assertIn(spec.runtime_key,TICK_RUNTIME_KEYS)
            self.assertTrue(strategy_adapter_v3(spec.runtime_key).live_route_enabled)
            self.assertFalse(live_config_issues_v3(strategy_key=key,timeframe="1m",
                control_mode="Manuell",modifiers=()))
            self.assertTrue(sim_config_issues_v3(strategy_key=key,timeframe="1m",
                control_mode="Manuell",modifiers=()))
            self.assertFalse(live_config_issues_v3(strategy_key=key,timeframe="1m",
                control_mode="Manuell",modifiers=("account-loss-lock",)))
            self.assertTrue(live_config_issues_v3(strategy_key=key,timeframe="1m",
                control_mode="Manuell",modifiers=("reset-on-loss",)))
            self.assertTrue(live_config_issues_v3(strategy_key=key,timeframe="5m",
                control_mode="Manuell",modifiers=()))
        source=Path("autotrader_v3_tick_shadow_live_v1.py").read_text()
        for forbidden in ("broker.place_order(","SaxoOrderRequest(","set_live_enabled_v3("):
            self.assertNotIn(forbidden,source)

    def test_live_durable_entry_and_signal_log_without_account_arm(self):
        for side,key in (("LONG",IMPULSE_LONG_CATALOG_KEY),
                         ("SHORT",IMPULSE_SHORT_CATALOG_KEY)):
            with self.subTest(side=side),TemporaryDirectory() as d:
                db=str(Path(d)/"test.db")
                recorder=HyperQuoteRecorder(db)
                ensure_order_guard(db)
                current=0.
                for tick,(at,mid) in enumerate(calm_and_impulse(side)):
                    recorder.observe(SimpleNamespace(market="US Tech 100 NAS",
                        uic=4912,asset_type="CfdOnIndex",bid=mid-.5,ask=mid+.5,
                        observed_at=at),tradable=True,now=at)
                    decision=evaluate_tick_live_v3(
                        trader_id="pilot",strategy_key=key,account_uic=4912,
                        asset_type="CfdOnIndex",actual_amount=current,
                        tranche=.01,db_path=db,now=at)
                    wanted=decision.decision.target.amount
                    self.assertIn(wanted,(0.,.01 if side=="LONG" else -.01))
                    if decision.decision.action=="TICK_"+side:
                        current=wanted
                    if decision.decision.action=="TICK_FLAT":
                        current=0.
                with connect(db) as conn:
                    events=conn.execute("""SELECT action,direction,window_seconds
                        FROM pg_v3_impulse_signal_events
                        WHERE trader_id='pilot' ORDER BY quote_at""").fetchall()
                self.assertTrue(any(e["action"]=="QUALIFIED_IMPULSE" for e in events))
                self.assertTrue(any(e["action"]=="IMPULSE_EXHAUSTED" for e in events))
                self.assertTrue(all(e["direction"]==side for e in events))

    def test_opposite_existing_position_blocks_without_liquidating(self):
        with TemporaryDirectory() as d:
            db=str(Path(d)/"test.db")
            decision=evaluate_tick_live_v3(
                trader_id="pilot",strategy_key=IMPULSE_LONG_CATALOG_KEY,
                account_uic=4912,asset_type="CfdOnIndex",actual_amount=-.01,
                tranche=.01,db_path=db,now=START)
            self.assertEqual(decision.decision.action,"BLOCK_OPPOSITE_INVENTORY")
            self.assertEqual(decision.decision.target.amount,-.01)


if __name__=="__main__":
    unittest.main()
