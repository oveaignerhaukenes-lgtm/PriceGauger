"""PAPER structural gate must detect extended decline despite MACD rebound."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime,timedelta,timezone
from unittest import TestCase

from autotrader_price_structure_regime_paper_v1 import (
    price_structure_regime_paper,structural_entry_allowed_paper,
)
from trading_desk import ChartBar


START=datetime(2026,11,19,tzinfo=timezone.utc)


def trend_bars(side=-1,count=401,bounce=0):
    rows=[]
    for i in range(count):
        price=27500+side*2.5*i+bounce*max(0,i-count+12)
        rows.append(ChartBar(market="US Tech 100 NAS",
             bar_time=START+timedelta(minutes=i),
             open=price,high=price+3,low=price-3,close=price,volume=None))
    return tuple(rows)


def classify(bars,cutoff=None):
    return price_structure_regime_paper(
        source_bars=bars,market_name="US Tech 100 NAS",
        cutoff=cutoff or START+timedelta(minutes=len(bars)))


class StructuralRegimePaperTests(TestCase):
    def test_falling_prices_remain_bearish_despite_short_rebound(self):
        result=classify(trend_bars(bounce=4.))
        self.assertEqual(result.state,"BEAR")
        self.assertFalse(structural_entry_allowed_paper(side="LONG",regime=result))
        self.assertTrue(structural_entry_allowed_paper(side="SHORT",regime=result))

    def test_rising_prices_are_symmetric(self):
        result=classify(trend_bars(side=1))
        self.assertEqual(result.state,"BULL")
        self.assertTrue(structural_entry_allowed_paper(side="LONG",regime=result))
        self.assertFalse(structural_entry_allowed_paper(side="SHORT",regime=result))

    def test_chop_or_insufficient_bars_fail_open_not_speculative_stop(self):
        bars=trend_bars()
        self.assertEqual(classify(bars[:300]).state,"UKJENT")
        sideways=tuple(replace(b,open=27000+(i%3),high=27005+(i%3),
                                low=26995+(i%3),close=27000+(i%3))
                       for i,b in enumerate(bars))
        result=classify(sideways)
        self.assertEqual(result.state,"UKJENT")
        for side in ("LONG","SHORT"):
            self.assertTrue(structural_entry_allowed_paper(side=side,regime=result))

    def test_missing_minute_invalidates_structure(self):
        rows=trend_bars()
        missing=rows[:170]+rows[171:]
        self.assertEqual(classify(missing,cutoff=START+timedelta(minutes=401)).state,"UKJENT")

    def test_future_changes_cannot_rewrite_past(self):
        rows=trend_bars()
        cutoff=START+timedelta(minutes=390)
        before=classify(rows,cutoff=cutoff)
        later=rows[:390]+tuple(replace(b,open=50000.,high=50005.,
                                      low=49995.,close=50000.) for b in rows[390:])
        self.assertEqual(before,classify(later,cutoff=cutoff))

    def test_invalid_side_rejected(self):
        with self.assertRaises(ValueError):
            structural_entry_allowed_paper(side="BOTH",regime=classify(trend_bars()))
