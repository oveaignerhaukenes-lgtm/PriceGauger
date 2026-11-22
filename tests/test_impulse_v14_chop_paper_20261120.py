"""Strict IC v1.4 PAPER entry veto: no missed breakout, no fake holding."""
from __future__ import annotations

from datetime import timedelta
from math import sin,pi
from unittest import TestCase

from autotrader_impulse_catcher_profiles_v1 import impulse_catcher_config
from autotrader_impulse_catcher_replay_v1 import ImpulseQuote,replay_impulse_catcher
from autotrader_impulse_catcher_v1 import ImpulseCatcherDecision
from autotrader_impulse_v14_chop_paper_v1 import ImpulseChopGatePaper
from tests.test_price_structure_regime_paper_20261120 import START


def oscillations(count=75):
    return tuple(ImpulseQuote(START+timedelta(seconds=i),
                 100+15*sin(i*2*pi/15)-.5,
                 100+15*sin(i*2*pi/15)+.5) for i in range(count))


def signal(*,side="LONG",mid=100.,at=70.,window=10,trigger=12.):
    return ImpulseCatcherDecision(side,"QUALIFIED_IMPULSE",mid,
                                  START+timedelta(seconds=at),trigger,3.,window)


class ImpulseV14ChopPaperTests(TestCase):
    def test_strict_observed_range_trap_is_blocked_both_sides(self):
        quotes=oscillations()
        for side in ("LONG","SHORT"):
            gate=ImpulseChopGatePaper(quotes,impulse_catcher_config(side,"1.3"))
            verdict=gate.evaluate(signal(side=side))
            self.assertFalse(verdict.allowed)
            self.assertEqual(verdict.reason,"RANGE_CHOP_TRAP")
            self.assertLessEqual(verdict.previous_efficiency,.20)
            self.assertGreaterEqual(verdict.reversals,4)

    def test_clear_impulse_breakout_from_same_chop_must_pass(self):
        quotes=oscillations()
        for side,mid in (("LONG",125.),("SHORT",75.)):
            gate=ImpulseChopGatePaper(quotes,impulse_catcher_config(side,"1.3"))
            self.assertTrue(gate.evaluate(signal(side=side,mid=mid)).allowed)

    def test_unknown_or_gapped_history_is_not_blocked(self):
        cfg=impulse_catcher_config("LONG","1.3")
        self.assertTrue(ImpulseChopGatePaper(oscillations(20),cfg)
                        .evaluate(signal()).allowed)
        gapped=tuple(q for i,q in enumerate(oscillations()) if i<27 or i>40)
        result=ImpulseChopGatePaper(gapped,cfg).evaluate(signal())
        self.assertTrue(result.allowed)
        self.assertEqual(result.reason,"UKJENT_PRIOR_WINDOW")

    def test_future_quotes_do_not_change_prior_gate_verdict(self):
        before=ImpulseChopGatePaper(oscillations(75),
                                    impulse_catcher_config("LONG","1.3"))
        after=ImpulseChopGatePaper(oscillations(110),
                                   impulse_catcher_config("LONG","1.3"))
        self.assertEqual(before.evaluate(signal()),after.evaluate(signal()))

    def test_no_veto_for_weak_or_out_of_range_conditions(self):
        gate=ImpulseChopGatePaper(oscillations(),impulse_catcher_config("LONG","1.3"))
        self.assertTrue(gate.evaluate(signal(trigger=30.)).allowed)
        self.assertTrue(gate.evaluate(signal(mid=125.,trigger=12.)).allowed)
        self.assertTrue(gate.evaluate(signal(window=0)).allowed)

    def test_veto_is_hypothetical_flat_not_ghost_inventory(self):
        cfg=impulse_catcher_config("LONG","1.3")
        ticks=tuple(ImpulseQuote(
            START+timedelta(seconds=i),
            100.+(.1*i if i<35 else 3.4+10*(i-34)),
            101.+(.1*i if i<35 else 3.4+10*(i-34))) for i in range(45))
        baseline=replay_impulse_catcher(ticks,cfg)
        allowed=replay_impulse_catcher(ticks,cfg,entry_allowed_asof=lambda _:True)
        blocked=replay_impulse_catcher(ticks,cfg,entry_allowed_asof=lambda _:False)
        self.assertEqual(baseline,allowed)
        self.assertGreater(baseline.signals,0)
        self.assertGreater(blocked.blocked_entries,0)
        self.assertEqual(blocked.unfilled_entries,0)
        self.assertEqual(blocked.unfinished_positions,0)
        self.assertFalse(blocked.trades)
        with self.assertRaisesRegex(ValueError,"entry policy"):
            replay_impulse_catcher(ticks,cfg,entry_allowed_asof=lambda _:None)

    def test_wrong_side_is_not_misclassified_as_entry(self):
        gate=ImpulseChopGatePaper(oscillations(),impulse_catcher_config("LONG","1.3"))
        with self.assertRaisesRegex(ValueError,"matching entry"):
            gate.evaluate(signal(side="SHORT"))

