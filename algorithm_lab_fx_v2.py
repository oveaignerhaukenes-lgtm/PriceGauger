"""Exact-UIC historical direct NOK FX rates for research conversion.

A RATE row at minute T is known only at its completed 1m close T+1m.
Never forward-fill a stale rate beyond 5 minutes. This models an as-of
currency-conversion scenario, not broker P/L ledger or overnight FX financing.
"""
from __future__ import annotations

from bisect import bisect_right
from datetime import timedelta
from math import isfinite

from algorithm_lab_v1 import utc


class HistoricalFXCurve:
    def __init__(self, bars, *, reference_at):
        self.times=[]
        self.rates=[]
        previous=None
        for bar in sorted(bars,key=lambda x:utc(x.bar_time)):
            t=utc(bar.bar_time)+timedelta(minutes=1)
            rate=float(bar.close)
            if (previous is not None and t<=previous or not isfinite(rate)
                    or not 0.000001<=rate<=1000000):
                raise ValueError("Invalid historical FX rate or ordering.")
            self.times.append(t)
            self.rates.append(rate)
            previous=t
        if not self.times:
            raise ValueError("No recorded direct-NOK FX history.")
        self.reference=self.rate_at(reference_at)

    def rate_at(self, stamp):
        t=utc(stamp)
        pos=bisect_right(self.times,t)-1
        if pos<0 or t-self.times[pos]>timedelta(minutes=5):
            raise ValueError("FX data missing/stale at research timestamp; cannot assume conversion.")
        return self.rates[pos]

    def factor(self, stamp):
        return self.rate_at(stamp)/self.reference


__all__=["HistoricalFXCurve"]
