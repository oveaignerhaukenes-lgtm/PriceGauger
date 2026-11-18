"""Patient-exit variants must preserve v1.1 entries and LIVE safety gates."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from autotrader_impulse_catcher_profiles_v1 import impulse_catcher_config
from autotrader_impulse_catcher_v1 import ImpulseCatcher
from autotrader_impulse_catcher_replay_v1 import (
    ImpulseQuote, replay_impulse_catcher, entry_regime_asof,
)
from autotrader_v3_registry_v1 import (
    live_config_issues_v3, sim_config_issues_v3, strategy_v3,
)
from autotrader_v3_tick_shadow_live_v1 import (
    IMPULSE_PATIENT_CATALOG_KEYS, TICK_CATALOG_KEYS, TICK_RUNTIME_KEYS,
    _decode_model, _encode_model, _new_model, evaluate_tick_live_v3,
)
from autotrader_v3_order_guard_v1 import ensure_schema as ensure_order_guard
from autotrader_v3_strategy_registry_v1 import strategy_adapter_v3
from database import connect
from live_sim_hyper_quotes_v1 import HyperQuoteRecorder


START=datetime(2026,11,18,12,0,tzinfo=timezone.utc)


def held_model(side,version):
    model=ImpulseCatcher(impulse_catcher_config(side,version))
    model.target=side
    model.entry_mid=100.
    model.extreme=120. if side=="LONG" else 80.
    model.last_extreme_at=START
    return model


def quote(model,seconds,mid):
    at=START+timedelta(seconds=seconds)
    return model.on_quote(at,mid-.5,mid+.5)


class PatientExitVersionsTest(unittest.TestCase):
    def test_same_entry_parameters_and_old_exit_unmodified(self):
        old=impulse_catcher_config("SHORT","1.1")
        v12=impulse_catcher_config("SHORT","1.2")
        v13=impulse_catcher_config("SHORT","1.3")
        self.assertEqual(old.exhaustion_seconds,2.0)
        self.assertEqual(v12.exhaustion_seconds,6.0)
        self.assertEqual(v13.exhaustion_seconds,6.0)
        for cfg in (v12,v13):
            for name in ("windows_seconds","history_seconds","min_impulse_points",
                         "relative_impulse_multiple","minimum_directional_efficiency",
                         "maximum_spread_points","spread_impulse_multiple",
                         "quote_gap_seconds","urgent_retrace_points","cooldown_seconds"):
                self.assertEqual(getattr(cfg,name),getattr(old,name),name)
        self.assertEqual(old.exit_confirmation_seconds,0.0)

    def test_v12_survives_shallow_pullback_then_exits_after_six_seconds(self):
        for side in ("LONG","SHORT"):
            d=1 if side=="LONG" else -1
            old=held_model(side,"1.1")
            slow=held_model(side,"1.2")
            for second in range(1,7):
                p=100+d*16  # 4 points off the favorable extreme
                a=quote(old,second,p)
                b=quote(slow,second,p)
                if second==2:
                    self.assertEqual(a.reason,"IMPULSE_EXHAUSTED")
                    self.assertIsNone(b)
                if second==6:
                    self.assertEqual(b.reason,"IMPULSE_EXHAUSTED")

    def test_v13_needs_persistent_retrace_not_one_flicker(self):
        for side in ("LONG","SHORT"):
            d=1 if side=="LONG" else -1
            fixed=held_model(side,"1.2")
            confirmed=held_model(side,"1.3")
            for second in range(1,10):
                # First five seconds stay below 4-point retrace threshold.
                price=100+d*(18 if second<=5 else 16)
                a=quote(fixed,second,price)
                b=quote(confirmed,second,price)
                if second==6:
                    self.assertIsNotNone(a)
                    self.assertEqual(a.target,"FLAT")
                    self.assertIsNone(b)
                if second==9:
                    self.assertEqual(b.reason,"IMPULSE_EXHAUSTED")

    def test_all_versions_keep_emergency_exit_and_quote_gap(self):
        for version in ("1.1","1.2","1.3"):
            for side in ("LONG","SHORT"):
                d=1 if side=="LONG" else -1
                model=held_model(side,version)
                self.assertEqual(quote(model,1,100+d*6).reason,"IMPULSE_EXHAUSTED")
                model=held_model(side,version)
                quote(model,0,100+d*20)
                self.assertEqual(quote(model,9,100+d*20).reason,"QUOTE_GAP_FLAT")

    def test_registry_live_routing_state_isolation_and_safe_ui_contract(self):
        self.assertEqual(len(IMPULSE_PATIENT_CATALOG_KEYS),4)
        for version in ("1.2","1.3"):
            for side in ("LONG","SHORT"):
                key=f"impulse-catcher-{side.lower()}-v{version.replace('.','-')}"
                self.assertIn(key,TICK_CATALOG_KEYS)
                spec=strategy_v3(key)
                self.assertIn(spec.runtime_key,TICK_RUNTIME_KEYS)
                self.assertTrue(strategy_adapter_v3(spec.runtime_key).live_route_enabled)
                self.assertFalse(live_config_issues_v3(strategy_key=key,timeframe="1m",
                                                       control_mode="Manuell",modifiers=()))
                self.assertTrue(live_config_issues_v3(strategy_key=key,timeframe="5m",
                                                      control_mode="Manuell",modifiers=()))
                self.assertTrue(live_config_issues_v3(strategy_key=key,timeframe="1m",
                                                      control_mode="Manuell",modifiers=("reset-on-loss",)))
                self.assertTrue(sim_config_issues_v3(strategy_key=key,timeframe="1m",
                                                     control_mode="Manuell",modifiers=()))
                model=_new_model(key)
                self.assertEqual(model.config.side,side)
                self.assertEqual(model.config.exhaustion_seconds,6.)
                model.target=side
                model.entry_mid=30000.
                model.extreme=30010. if side=="LONG" else 29990.
                model.last_extreme_at=START
                model.samples.append((START,30000.))
                restored=_decode_model(key,_encode_model(key,model))
                self.assertEqual(restored.config,model.config)
                self.assertEqual(restored.target,model.target)

    def test_replay_next_quote_and_same_causal_entries(self):
        for side in ("LONG","SHORT"):
            d=1 if side=="LONG" else -1
            mids=[30000.+(i%3)*.5 for i in range(100)]
            for i in range(64,71):
                mids[i]=30000+d*((i-63)*6)
            for i in range(71,100):
                mids[i]=30000+d*(42-min(12,(i-70)*2))
            quotes=tuple(ImpulseQuote(START+timedelta(seconds=i),p-.5,p+.5)
                         for i,p in enumerate(mids))
            results={v:replay_impulse_catcher(quotes,impulse_catcher_config(side,v))
                     for v in ("1.1","1.2","1.3")}
            self.assertTrue(all(r.signals>=1 and len(r.trades)>=1
                                for r in results.values()))
            self.assertEqual(len({r.trades[0].signal_at for r in results.values()
                                  if r.trades}),1)
            self.assertTrue(all(not r.trades or
                                r.trades[0].filled_at>r.trades[0].signal_at
                                for r in results.values()))

    def test_regime_is_only_past_quotes_and_gaps_remain_unknown(self):
        stable=tuple(ImpulseQuote(START+timedelta(seconds=i),100.+i,101.+i)
                     for i in range(90))
        self.assertEqual(entry_regime_asof(stable,START+timedelta(seconds=59)),"TREND")
        # Suffix values that occur strictly AFTER signal must never matter.
        later=stable[:60]+tuple(ImpulseQuote(q.at,200.-i*4,201.-i*4)
                                for i,q in enumerate(stable[60:]))
        self.assertEqual(entry_regime_asof(later,START+timedelta(seconds=59)),"TREND")
        alternating=tuple(ImpulseQuote(q.at,100.+(i%2),101.+(i%2))
                          for i,q in enumerate(stable))
        self.assertEqual(entry_regime_asof(alternating,START+timedelta(seconds=59)),"SIDEVEIS")
        gaps=stable[:25]+stable[40:]
        self.assertEqual(entry_regime_asof(gaps,START+timedelta(seconds=59)),"UKJENT")

    def test_v12_v13_process_thirty_seconds_of_real_bbo_without_false_gap(self):
        for version in ("1.2","1.3"):
            key=f"impulse-catcher-short-v{version.replace('.','-')}"
            with self.subTest(version=version),TemporaryDirectory() as tmp:
                db=str(Path(tmp)/"quotes.db")
                recorder=HyperQuoteRecorder(db)
                ensure_order_guard(db)
                for second in range(31):
                    at=START+timedelta(seconds=second)
                    recorder.observe(SimpleNamespace(market="US Tech 100 NAS",
                        uic=4912,asset_type="CfdOnIndex",bid=29999.25-second,
                        ask=30000.75-second,observed_at=at),tradable=True,now=at)
                    if second==0:
                        first=evaluate_tick_live_v3(trader_id="pilot",strategy_key=key,
                            account_uic=4912,asset_type="CfdOnIndex",actual_amount=-.01,
                            tranche=.01,db_path=db,now=at).decision
                        self.assertEqual(first.action,"BOOTSTRAP")
                result=evaluate_tick_live_v3(trader_id="pilot",strategy_key=key,
                    account_uic=4912,asset_type="CfdOnIndex",actual_amount=-.01,
                    tranche=.01,db_path=db,now=START+timedelta(seconds=30)).decision
                self.assertEqual(result.action,"HOLD_SHORT")
                with connect(db) as conn:
                    row=conn.execute("SELECT strategy_key FROM pg_v3_tick_live_state "
                                     "WHERE trader_id=?",("pilot",)).fetchone()
                self.assertEqual(row["strategy_key"],key)


if __name__=="__main__":
    unittest.main()
