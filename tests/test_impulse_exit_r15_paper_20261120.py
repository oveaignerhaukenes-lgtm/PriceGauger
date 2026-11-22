"""Only PAPER: completed R15 chronology, asymmetric exit, safety invariants."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import unittest

from autotrader_impulse_catcher_profiles_v1 import impulse_catcher_config
from autotrader_impulse_catcher_replay_v1 import ImpulseQuote, replay_impulse_catcher
from autotrader_impulse_catcher_v1 import ImpulseCatcher
from autotrader_impulse_exit_regime_paper_v1 import (
    PAPER_EXIT_MODES, paper_exit_config_for_quote,
    r15_timeline_from_closed_1m_paper,
)
from trading_desk import ChartBar


START = datetime(2026, 11, 19, 0, 0, tzinfo=timezone.utc)


def downward_minute_bars(count=600):
    rows = []
    for i in range(count):
        price = 30000.0 - 0.05 * i - 0.0002 * i * i
        rows.append(ChartBar(market="US Tech 100 NAS",
                             bar_time=START + timedelta(minutes=i),
                             open=price + .2, high=price + .5,
                             low=price - .5, close=price, volume=None))
    return tuple(rows)


class ImpulseExitR15PaperTest(unittest.TestCase):
    def test_only_full_r15_macd_with_35_bar_warmup_and_freshness(self):
        bars = downward_minute_bars()
        timeline = r15_timeline_from_closed_1m_paper(
            source_bars=bars, cutoff=START + timedelta(minutes=540),
            market_name="US Tech 100 NAS")
        self.assertEqual(timeline.state_asof(START + timedelta(minutes=524)), "UKJENT")
        self.assertEqual(timeline.state_asof(START + timedelta(minutes=525)), "BEAR")
        self.assertEqual(timeline.state_asof(START + timedelta(minutes=540)), "BEAR")
        self.assertEqual(timeline.state_asof(START + timedelta(minutes=555)), "UKJENT")

    def test_future_prices_cannot_affect_past_r15(self):
        bars = downward_minute_bars()
        before = r15_timeline_from_closed_1m_paper(
            source_bars=bars,cutoff=START + timedelta(minutes=585),
            market_name="US Tech 100 NAS")
        later = list(bars)
        for i in range(585,600):
            later[i] = replace(later[i],open=30000+i,high=30001+i,
                               low=29999+i,close=30000+i)
        after = r15_timeline_from_closed_1m_paper(
            source_bars=later,cutoff=START + timedelta(minutes=600),
            market_name="US Tech 100 NAS")
        for i in range(0,585):
            point = START + timedelta(minutes=i)
            self.assertEqual(before.state_asof(point),after.state_asof(point))

    def test_one_missing_minute_does_not_fabricate_r15_candle(self):
        rows=tuple(b for i,b in enumerate(downward_minute_bars()) if i!=420)
        timeline=r15_timeline_from_closed_1m_paper(
            source_bars=rows,cutoff=START+timedelta(minutes=600),
            market_name="US Tech 100 NAS")
        self.assertEqual(timeline.closed_at,())

    def test_asymmetry_and_urgent_exit_unchanged(self):
        self.assertEqual(len(PAPER_EXIT_MODES),4)
        for side in ("LONG","SHORT"):
            base=impulse_catcher_config(side,"1.3")
            for mode in PAPER_EXIT_MODES:
                for state in ("BEAR","BULL","UKJENT"):
                    proposed=paper_exit_config_for_quote(
                        side=side,mode=mode,r15_state=state)
                    for field in (
                        "min_impulse_points","relative_impulse_multiple",
                        "minimum_directional_efficiency","windows_seconds",
                        "quote_gap_seconds","urgent_retrace_points",
                        "cooldown_seconds","exit_noise_multiple",
                        "exit_confirmation_seconds",
                    ):
                        self.assertEqual(getattr(base,field),getattr(proposed,field))
                    model=ImpulseCatcher(proposed,target=side,entry_mid=100.,
                        extreme=(120. if side=="LONG" else 80.),
                        last_extreme_at=START)
                    adverse=(106. if side=="LONG" else 94.)
                    exit_signal=model.on_quote(START+timedelta(seconds=1),
                                               adverse-.5,adverse+.5)
                    self.assertIsNotNone(exit_signal)
                    self.assertEqual(exit_signal.reason,"IMPULSE_EXHAUSTED")
        self.assertEqual(paper_exit_config_for_quote(
            side="SHORT",mode="r15_short_bear_venter_5s",
            r15_state="BEAR").exhaustion_seconds,11.)
        self.assertEqual(paper_exit_config_for_quote(
            side="LONG",mode="r15_short_bear_venter_5s",
            r15_state="BEAR").exhaustion_seconds,6.)
        self.assertEqual(paper_exit_config_for_quote(
            side="LONG",mode="r15_medvind_venter_motvind_rask",
            r15_state="BEAR").exhaustion_seconds,3.)

    def test_replay_exit_callback_refuses_entry_or_safety_changes(self):
        ticks=tuple(ImpulseQuote(START+timedelta(seconds=i),100.+i,101.+i)
                    for i in range(15))
        cfg=impulse_catcher_config("LONG","1.3")
        baseline=replay_impulse_catcher(ticks,cfg)
        same=replay_impulse_catcher(ticks,cfg,exit_config_asof=lambda _:cfg)
        self.assertEqual(baseline,same)
        bad=replace(cfg,quote_gap_seconds=30.)
        with self.assertRaisesRegex(ValueError,"quote_gap_seconds"):
            replay_impulse_catcher(ticks,cfg,exit_config_asof=lambda _:bad)
        bad_entry=replace(cfg,min_impulse_points=1.)
        with self.assertRaisesRegex(ValueError,"min_impulse_points"):
            replay_impulse_catcher(ticks,cfg,exit_config_asof=lambda _:bad_entry)

    def test_shallow_short_retrace_baseline_exits_but_bearish_patient_waits(self):
        base=ImpulseCatcher(impulse_catcher_config("SHORT","1.3"),
                            target="SHORT",entry_mid=100.,extreme=80.,
                            last_extreme_at=START)
        patient=ImpulseCatcher(paper_exit_config_for_quote(
            side="SHORT",mode="r15_short_bear_venter_5s",r15_state="BEAR"),
            target="SHORT",entry_mid=100.,extreme=80.,last_extreme_at=START)
        for second in range(1,11):
            at=START+timedelta(seconds=second)
            first=base.on_quote(at,84.5,85.5)
            second_decision=patient.on_quote(at,84.5,85.5)
            if second==6:
                self.assertIsNotNone(first)
                self.assertEqual(first.reason,"IMPULSE_EXHAUSTED")
                self.assertIsNone(second_decision)
        self.assertEqual(base.target,"FLAT")
        self.assertEqual(patient.target,"SHORT")
        # New favorable extreme during the extra 5s resets normal exit wait.
        at=START+timedelta(seconds=11)
        self.assertIsNone(patient.on_quote(at,77.5,78.5))
        self.assertEqual(patient.extreme,78.)


if __name__ == "__main__":
    unittest.main()
