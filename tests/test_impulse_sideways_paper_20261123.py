"""Sideways-only and rare-shock Impulse Catcher candidates are PAPER-only."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest import TestCase

from autotrader_impulse_catcher_profiles_v1 import impulse_catcher_config
from autotrader_impulse_catcher_replay_v1 import ImpulseQuote, replay_impulse_catcher
from autotrader_impulse_catcher_v1 import ImpulseCatcherDecision
from autotrader_impulse_sideways_paper_v1 import (
    SIDEWAYS, TRANSITION, TREND_BEAR, TREND_BULL, UNKNOWN,
    SidewaysContextPaper, SidewaysTimelinePaper, SpecializedICEntryGatePaper,
    classify_sideways_context_paper, specialized_ic_config_paper,
    sideways_timeline_paper,
)

START = datetime(2026, 11, 23, 9, 0, tzinfo=timezone.utc)


def bars(moves, *, start=START):
    price = 26000.
    result = [SimpleNamespace(bar_time=start, open=price,
                              high=price+1., low=price-1., close=price)]
    for i, movement in enumerate(moves, start=1):
        old, price = price, price + movement
        result.append(SimpleNamespace(
            bar_time=start+timedelta(minutes=i),open=old,
            high=max(old,price)+1,low=min(old,price)-1,close=price))
    return tuple(result)


def sample_quotes(count=100):
    return tuple(ImpulseQuote(START+timedelta(seconds=i),
                              26000+i-.5,26000+i+.5) for i in range(count))


def state_timeline(state):
    return SidewaysTimelinePaper((START+timedelta(seconds=65),),
                                 (SidewaysContextPaper(state, "TEST"),))


def signal(side="LONG", *, at=START+timedelta(seconds=70),
           mid=26070.,trigger=32.,baseline=4.,window=3):
    return ImpulseCatcherDecision(side,"QUALIFIED_IMPULSE",mid,at,
                                  trigger,baseline,window)


class SidewaysSpecializationsPaperTests(TestCase):
    def test_sideways_is_confirmed_by_range_not_confused_with_transition(self):
        self.assertEqual(classify_sideways_context_paper(bars([15,-15]*30)).state,SIDEWAYS)
        self.assertEqual(classify_sideways_context_paper(bars([15,-15]*15)).state,SIDEWAYS)
        self.assertEqual(classify_sideways_context_paper(bars([4]*60)).state,TREND_BULL)
        self.assertEqual(classify_sideways_context_paper(bars([-4]*60)).state,TREND_BEAR)
        self.assertEqual(classify_sideways_context_paper(
            bars([-4]*30+[1]*30)).state,TRANSITION)

    def test_incomplete_and_gapped_bars_cannot_claim_sideways(self):
        full = bars([15,-15]*30)
        self.assertEqual(classify_sideways_context_paper(full[:30]).state,UNKNOWN)
        self.assertEqual(classify_sideways_context_paper(full[:20]+full[21:]).state,UNKNOWN)
        self.assertEqual(classify_sideways_context_paper(full[::-1]).state,UNKNOWN)
        self.assertEqual(classify_sideways_context_paper(bars([0]*60)).state,UNKNOWN)

    def test_asof_uses_only_closed_bars_and_does_not_forward_fill(self):
        source=bars([15,-15]*60)
        cutoff=source[65].bar_time+timedelta(minutes=1)
        before=sideways_timeline_paper(source_bars=source[:66],
                                       cutoff=cutoff,market_name="Tech100")
        with_future=sideways_timeline_paper(source_bars=source,
                                            cutoff=cutoff,market_name="Tech100")
        asof=source[61].bar_time+timedelta(minutes=1)
        self.assertEqual(before.state_asof(asof),with_future.state_asof(asof))
        self.assertEqual(before.state_asof(asof).state,SIDEWAYS)
        self.assertEqual(before.state_asof(asof-timedelta(seconds=1)).state,SIDEWAYS)
        self.assertEqual(before.state_asof(START+timedelta(minutes=29)).state,UNKNOWN)
        self.assertEqual(before.state_asof(asof+timedelta(minutes=1)).state,SIDEWAYS)
        self.assertEqual(before.state_asof(cutoff+timedelta(minutes=2)).state,UNKNOWN)

    def test_specialized_thresholds_and_safety_exits_are_separate(self):
        for side in ("LONG","SHORT"):
            baseline=impulse_catcher_config(side,"1.3")
            variant=specialized_ic_config_paper(side)
            self.assertGreater(variant.min_impulse_points,baseline.min_impulse_points)
            self.assertGreater(variant.relative_impulse_multiple,baseline.relative_impulse_multiple)
            self.assertGreater(variant.minimum_directional_efficiency,
                               baseline.minimum_directional_efficiency)
            self.assertGreater(variant.exhaustion_seconds,baseline.exhaustion_seconds)
            self.assertGreater(variant.cooldown_seconds,baseline.cooldown_seconds)
            self.assertEqual(variant.quote_gap_seconds,baseline.quote_gap_seconds)
            self.assertEqual(variant.maximum_spread_points,baseline.maximum_spread_points)

    def test_confirmed_sideways_passes_only_nontraps(self):
        quotes=sample_quotes()
        cfg=specialized_ic_config_paper("LONG")
        gate=SpecializedICEntryGatePaper(quotes=quotes,config=cfg,
                 timeline=state_timeline(SIDEWAYS),mode="sideways_only")
        self.assertTrue(gate.evaluate(signal()).allowed)
        for unknown in (UNKNOWN,TRANSITION,TREND_BULL,TREND_BEAR):
            gate=SpecializedICEntryGatePaper(quotes=quotes,config=cfg,
                     timeline=state_timeline(unknown),mode="sideways_only")
            self.assertFalse(gate.evaluate(signal()).allowed)

    def test_rare_shock_opposite_only_with_exceptional_breakout(self):
        quotes=sample_quotes()
        cfg=specialized_ic_config_paper("LONG")
        gate=SpecializedICEntryGatePaper(quotes=quotes,config=cfg,
                 timeline=state_timeline(TREND_BEAR),mode="sideways_plus_shock")
        self.assertTrue(gate.evaluate(signal(mid=26200.)).allowed)
        self.assertFalse(gate.evaluate(signal(mid=26065.)).allowed)
        self.assertFalse(gate.evaluate(signal(mid=26200.,trigger=18.)).allowed)
        self.assertFalse(gate.evaluate(signal(mid=26200.,window=10)).allowed)
        same=SpecializedICEntryGatePaper(quotes=quotes,config=cfg,
                 timeline=state_timeline(TREND_BULL),mode="sideways_plus_shock")
        self.assertFalse(same.evaluate(signal(mid=26200.)).allowed)

    def test_shock_needs_contiguous_prior_quote_evidence(self):
        cfg=specialized_ic_config_paper("LONG")
        quotes=tuple(q for i,q in enumerate(sample_quotes()) if i<35 or i>60)
        gate=SpecializedICEntryGatePaper(quotes=quotes,config=cfg,
                 timeline=state_timeline(TREND_BEAR),mode="sideways_plus_shock")
        self.assertFalse(gate.evaluate(signal(mid=26200.)).allowed)

    def test_paper_replay_veto_never_creates_ghost_positions(self):
        quotes=tuple(ImpulseQuote(START+timedelta(seconds=i),
            25999.5+(0.15*i if i<180 else 27.+3.*(i-179)),
            26000.5+(0.15*i if i<180 else 27.+3.*(i-179))) for i in range(230))
        cfg=specialized_ic_config_paper("LONG")
        normal=replay_impulse_catcher(quotes,cfg)
        blocked=replay_impulse_catcher(quotes,cfg,entry_allowed_asof=lambda _:False)
        self.assertGreater(normal.signals,0)
        self.assertGreater(blocked.blocked_entries,0)
        self.assertEqual(blocked.unfilled_entries,0)
        self.assertEqual(blocked.unfinished_positions,0)
        self.assertEqual(len(blocked.trades),0)

    def test_weak_repeated_microbursts_trigger_fewer_entries_than_v13(self):
        # Quiet history, then repeated ~12pt 3s bursts. v1.3 can trade them;
        # the specialist requires >=15pt and stronger relative momentum.
        price=26000.
        quotes=[]
        for i in range(840):
            phase=i % 140
            if i>180 and phase in (40,41,42):
                price+=4.
            elif i>180 and 43<=phase<=66:
                price-=0.5
            else:
                price+=0.1 if i%2 else -0.1
            quotes.append(ImpulseQuote(START+timedelta(seconds=i),
                                       price-0.5,price+0.5))
        old=replay_impulse_catcher(tuple(quotes),impulse_catcher_config("LONG","1.3"))
        new=replay_impulse_catcher(tuple(quotes),specialized_ic_config_paper("LONG"))
        self.assertGreater(old.signals,0)
        self.assertLess(new.signals,old.signals)


if __name__=="__main__":
    import unittest
    unittest.main()
