"""PAPER only: structure-aware countertrend exit, without entry suppression."""
from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from unittest import TestCase

from autotrader_impulse_catcher_profiles_v1 import impulse_catcher_config
from autotrader_impulse_catcher_replay_v1 import ImpulseQuote, replay_impulse_catcher
from autotrader_impulse_catcher_v1 import ImpulseCatcher
from autotrader_impulse_exit_regime_paper_v1 import (
    STRUCTURE_EXIT_MODES, paper_structure_exit_config_for_quote,
)
from autotrader_price_structure_regime_paper_v1 import (
    price_structure_timeline_from_closed_1m_paper,
)
from tests.test_price_structure_regime_paper_20261120 import START, trend_bars


def timeline(rows, cutoff=None):
    return price_structure_timeline_from_closed_1m_paper(
        source_bars=rows,market_name="US Tech 100 NAS",
        cutoff=cutoff or START+timedelta(minutes=len(rows)))


class ImpulseStructuralExitTests(TestCase):
    def test_structural_bear_and_bull_use_only_closed_prices(self):
        down=timeline(trend_bars(count=401))
        up=timeline(trend_bars(side=1,count=401))
        self.assertEqual(down.state_asof(START+timedelta(minutes=360)),"UKJENT")
        self.assertEqual(down.state_asof(START+timedelta(minutes=361)),"BEAR")
        self.assertEqual(up.state_asof(START+timedelta(minutes=361)),"BULL")
        self.assertEqual(down.state_asof(START+timedelta(minutes=402)),"UKJENT")

    def test_future_change_cannot_rewrite_previous_state(self):
        bars=trend_bars(count=420)
        cutoff=START+timedelta(minutes=400)
        original=timeline(bars,cutoff=cutoff)
        modified=bars[:400]+tuple(replace(b,open=40000.,high=40003.,
                               low=39997.,close=40000.) for b in bars[400:])
        future=timeline(modified,cutoff=START+timedelta(minutes=420))
        for minute in (360,361,380,399):
            point=START+timedelta(minutes=minute)
            self.assertEqual(original.state_asof(point),future.state_asof(point))

    def test_gap_and_stale_history_never_carry_old_bear_forward(self):
        rows=trend_bars(count=430)
        missing=rows[:402]+rows[403:]
        t=timeline(missing,cutoff=START+timedelta(minutes=430))
        self.assertEqual(t.state_asof(START+timedelta(minutes=402)),"BEAR")
        self.assertEqual(t.state_asof(START+timedelta(minutes=403)),"UKJENT")
        self.assertEqual(t.state_asof(START+timedelta(minutes=404)),"UKJENT")
        self.assertEqual(t.state_asof(START+timedelta(minutes=430)),"UKJENT")

    def test_asymmetric_exits_do_not_change_entry_or_emergency_fields(self):
        self.assertEqual(len(STRUCTURE_EXIT_MODES),3)
        for side in ("LONG","SHORT"):
            baseline=impulse_catcher_config(side,"1.3")
            for mode in STRUCTURE_EXIT_MODES:
                for state in ("BEAR","BULL","UKJENT"):
                    cfg=paper_structure_exit_config_for_quote(
                        side=side,mode=mode,structure_state=state)
                    for field in (
                        "side","windows_seconds","history_seconds",
                        "min_impulse_points","relative_impulse_multiple",
                        "minimum_directional_efficiency","maximum_spread_points",
                        "spread_impulse_multiple","quote_gap_seconds",
                        "minimum_retrace_points","retrace_fraction",
                        "urgent_retrace_points","cooldown_seconds",
                        "exit_noise_multiple","exit_confirmation_seconds",
                    ):
                        self.assertEqual(getattr(cfg,field),getattr(baseline,field))
        self.assertEqual(paper_structure_exit_config_for_quote(
            side="LONG",mode="struktur_motvind_rask",
            structure_state="BEAR").exhaustion_seconds,3.)
        self.assertEqual(paper_structure_exit_config_for_quote(
            side="SHORT",mode="struktur_motvind_rask",
            structure_state="BEAR").exhaustion_seconds,6.)
        self.assertEqual(paper_structure_exit_config_for_quote(
            side="SHORT",mode="struktur_medvind_venter_motvind_rask",
            structure_state="BEAR").exhaustion_seconds,11.)
        self.assertEqual(paper_structure_exit_config_for_quote(
            side="LONG",mode="struktur_medvind_venter_motvind_rask",
            structure_state="UKJENT").exhaustion_seconds,6.)

    def test_countertrend_long_exit_faster_but_emergency_still_immediate(self):
        baseline=ImpulseCatcher(impulse_catcher_config("LONG","1.3"),
            target="LONG",entry_mid=100.,extreme=120.,last_extreme_at=START)
        fast_cfg=paper_structure_exit_config_for_quote(
            side="LONG",mode="struktur_motvind_rask",structure_state="BEAR")
        faster=ImpulseCatcher(fast_cfg,target="LONG",entry_mid=100.,
                              extreme=120.,last_extreme_at=START)
        for second in range(1,5):
            at=START+timedelta(seconds=second)
            normal_decision=baseline.on_quote(at,114.5,115.5)
            fast_decision=faster.on_quote(at,114.5,115.5)
        self.assertIsNone(normal_decision)
        self.assertIsNotNone(fast_decision)
        self.assertEqual(fast_decision.target,"FLAT")
        emergency=ImpulseCatcher(fast_cfg,target="LONG",entry_mid=100.,
                                 extreme=120.,last_extreme_at=START)
        self.assertEqual(emergency.on_quote(
            START+timedelta(seconds=1),105.5,106.5).target,"FLAT")

    def test_replay_never_removes_countertrend_entry_opportunity(self):
        cfg=impulse_catcher_config("LONG","1.3")
        ticks=tuple(ImpulseQuote(
            START+timedelta(seconds=i),
            100.+(.1*i if i<35 else 3.4+10*(i-34)),
            101.+(.1*i if i<35 else 3.4+10*(i-34))) for i in range(45))
        plain=replay_impulse_catcher(ticks,cfg)
        opposite=replay_impulse_catcher(ticks,cfg,exit_config_asof=lambda at:
            paper_structure_exit_config_for_quote(
                side="LONG",mode="struktur_motvind_rask",structure_state="BEAR"))
        self.assertGreater(plain.signals,0)
        self.assertEqual(plain.signals,opposite.signals)
        self.assertEqual(plain.unfilled_entries,opposite.unfilled_entries)
        self.assertEqual(plain.unfinished_positions,opposite.unfinished_positions)

