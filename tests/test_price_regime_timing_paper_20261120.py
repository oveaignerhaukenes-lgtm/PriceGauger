"""PAPER-only 30/60m price reversals over a separate 6h backdrop."""
from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from unittest import TestCase

from autotrader_price_regime_timing_paper_v1 import price_regime_timing_timeline_paper
from tests.test_price_structure_regime_paper_20261120 import START, trend_bars
from trading_desk import ChartBar


MARKET="US Tech 100 NAS"


def from_bars(bars, cutoff=None):
    return price_regime_timing_timeline_paper(
        source_bars=bars,cutoff=cutoff or START+timedelta(minutes=len(bars)),
        market_name=MARKET)


def reversal(*, initial_side=-1, initial_count=400, initial_step=3.5, move_minutes=70,
             step=4., chop=False):
    bars=[]
    for i in range(initial_count):
        price=27500+initial_side*initial_step*i
        bars.append(ChartBar(market=MARKET,
            bar_time=START+timedelta(minutes=i),
            open=price,high=price+3.,low=price-3.,
            close=price,volume=None))
    previous=bars[-1].close
    for k in range(move_minutes):
        if chop:
            previous+=step*(1 if k%2==0 else -1)
        else:
            previous-=initial_side*step
        bars.append(ChartBar(market=MARKET,
            bar_time=START+timedelta(minutes=initial_count+k),
            open=previous,high=previous+3.,low=previous-3.,
            close=previous,volume=None))
    return tuple(bars)


class PriceRegimeTimingPaperTests(TestCase):
    def test_early_30min_bull_turn_without_waiting_for_six_hours(self):
        bars=trend_bars(side=1,count=35)
        timeline=from_bars(bars)
        early=timeline.state_asof(START+timedelta(minutes=31))
        self.assertEqual(early.primary,"UKJENT")
        self.assertEqual(early.local,"BULL_30")
        self.assertTrue(early.regime_long_allowed)
        self.assertAlmostEqual(early.mean_price_30,
                               sum(b.close for b in bars[1:31])/30)

    def test_short_rebound_does_not_overrule_clear_six_hour_bear(self):
        bars=reversal(move_minutes=12)
        timeline=from_bars(bars)
        before=timeline.state_asof(START+timedelta(minutes=400))
        later=timeline.state_asof(START+timedelta(minutes=412))
        self.assertEqual(before.primary,"BEAR")
        self.assertEqual(later.primary,"BEAR")
        self.assertNotIn(later.local,("BULL_30","BULL_60"))
        self.assertFalse(later.regime_long_allowed)
        self.assertTrue(later.regime_short_allowed)

    def test_strong_thirty_minute_breakout_allows_countertrend_long(self):
        timeline=from_bars(reversal())
        initial=timeline.state_asof(START+timedelta(minutes=411))
        early=timeline.state_asof(START+timedelta(minutes=431))
        self.assertEqual(initial.primary,"BEAR")
        self.assertFalse(initial.regime_long_allowed)
        self.assertEqual(early.primary,"BEAR")
        self.assertEqual(early.local,"BULL_30")
        self.assertTrue(early.regime_long_allowed)
        self.assertEqual(early.effective_for_impulse_exit,"UKJENT")

    def test_sustained_one_hour_turn_is_confirmed(self):
        timeline=from_bars(reversal())
        confirmed=timeline.state_asof(START+timedelta(minutes=461))
        self.assertEqual(confirmed.local,"BULL_60")
        self.assertTrue(confirmed.regime_long_allowed)
        self.assertEqual(confirmed.effective_for_impulse_exit,"BULL")

    def test_bearish_turn_is_symmetric(self):
        timeline=from_bars(reversal(initial_side=1))
        before=timeline.state_asof(START+timedelta(minutes=400))
        after30=timeline.state_asof(START+timedelta(minutes=431))
        after60=timeline.state_asof(START+timedelta(minutes=461))
        self.assertEqual(before.primary,"BULL")
        self.assertEqual(after30.local,"BEAR_30")
        self.assertTrue(after30.regime_short_allowed)
        self.assertEqual(after60.local,"BEAR_60")
        self.assertEqual(after60.effective_for_impulse_exit,"BEAR")

    def test_oscillation_has_no_false_bull_turn(self):
        timeline=from_bars(reversal(chop=True))
        for at in (430,450,470):
            state=timeline.state_asof(START+timedelta(minutes=at))
            self.assertEqual(state.primary,"BEAR")
            self.assertNotIn(state.local,("BULL_30","BULL_60"))
            self.assertFalse(state.regime_long_allowed)

    def test_bar_gap_expires_state_and_resets_warmup(self):
        bars=reversal()
        missing=bars[:435]+bars[436:]
        timeline=from_bars(missing,cutoff=START+timedelta(minutes=470))
        self.assertEqual(timeline.state_asof(
            START+timedelta(minutes=435)).local,"BULL_30")
        stale=timeline.state_asof(START+timedelta(minutes=437))
        self.assertEqual(stale.primary,"UKJENT")
        self.assertEqual(stale.local,"UKJENT")
        self.assertTrue(stale.regime_long_allowed)

    def test_future_bar_mutation_cannot_rewrite_history(self):
        bars=reversal()
        cutoff=START+timedelta(minutes=445)
        original=from_bars(bars,cutoff=cutoff)
        changed=bars[:445]+tuple(replace(b,open=50000.,high=50003.,
                                      low=49997.,close=50000.) for b in bars[445:])
        replay=from_bars(changed,cutoff=START+timedelta(minutes=len(changed)))
        for minute in (395,410,431,440,445):
            at=START+timedelta(minutes=minute)
            self.assertEqual(original.state_asof(at),replay.state_asof(at))

