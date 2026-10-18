"""Tests for research-only, past-observation cycle diagnostics."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from market_rhythm_wavelet_research_v1 import (
    PERIODS_MIN, causal_morlet_bank_v1, latest_lag_correlation_v1,
    build_cycle_research_v1,
)
from navigation_config import PAGE_GROUPS


START = pd.Timestamp("2026-10-16T08:00:00Z")


def _series(values):
    return pd.Series(
        values,
        index=pd.date_range(START,periods=len(values),freq="1min"),
        dtype=float,
    )


def test_synthetic_12m_wave_has_strong_12m_wavelet_rhythm():
    t=np.arange(640,dtype=float)
    prices=_series(100.0+1.2*np.sin(2*np.pi*t/12.0))
    readout=build_cycle_research_v1(prices)
    assert readout.contiguous_bars==640
    assert readout.normalized_power[12].iloc[-1] > 0
    assert readout.normalized_power[12].iloc[-1] > readout.normalized_power[64].iloc[-1]
    assert readout.dominant_wavelet_minutes is not None
    assert readout.lag_correlation_minutes in PERIODS_MIN
    assert readout.lag_correlation is not None and readout.lag_correlation>0.65
    assert readout.confirmed_turns


def test_causal_wavelet_no_future_bar_can_change_earlier_readout():
    t=np.arange(500,dtype=float)
    base=_series(100+np.sin(t*2*np.pi/16))
    before=causal_morlet_bank_v1(base.iloc[:330])
    after=causal_morlet_bank_v1(base)
    pd.testing.assert_frame_equal(before,after.loc[before.index])


def test_flat_prices_do_not_fabricate_dominant_market_cycle():
    result=build_cycle_research_v1(_series([100.0]*450))
    assert result.dominant_wavelet_minutes is None
    assert result.lag_correlation_minutes is None
    assert result.lag_correlation is None
    assert result.confirmed_turns==()
    assert result.wavelet_contrast is None


def test_missing_data_splits_sessions_never_interpolates_weekend():
    p1=_series([100+np.sin(i*2*np.pi/12) for i in range(300)])
    p2=_series([100+np.sin(i*2*np.pi/12) for i in range(350)])
    p2.index = p2.index+pd.Timedelta(days=2)
    prices=pd.concat([p1,p2])
    state=build_cycle_research_v1(prices)
    assert state.cut_at_gap
    assert state.total_input_bars==650
    assert state.contiguous_bars==350
    assert state.prices.index[0]==p2.index[0]
    assert state.prices.index[-1]==p2.index[-1]


def test_under_two_or_three_periods_returns_unknown_instead_of_zero():
    prices=_series([100.0+np.sin(i/5) for i in range(26)])
    bank=causal_morlet_bank_v1(prices,periods=(4,12))
    assert np.isnan(bank[12].iloc[-1])
    profile=build_cycle_research_v1(prices)
    assert profile.lag_correlation_minutes is None


def test_no_duplicate_or_nonpositive_candle_timestamps():
    prices=_series([99.0,100.0,101.0])
    repeat=pd.concat([prices,prices.tail(1)])
    with pytest.raises(ValueError,match="unique"):
        build_cycle_research_v1(repeat)
    with pytest.raises(ValueError):
        causal_morlet_bank_v1(pd.Series([1.0,2.0,3.0]))


def test_nav_and_research_page_dont_mutate_live_strategies_or_saxo():
    item=next(x for x in PAGE_GROUPS["Analyse"] if x["title"]=="Sykluslaboratorium")
    assert item["page"]=="pages/0_Cycle_Research.py"
    assert item["url_path"]=="Cycle_Research"
    page=Path("pages/0_Cycle_Research.py").read_text(encoding="utf-8")
    research=Path("market_rhythm_wavelet_research_v1.py").read_text(encoding="utf-8")
    assert "CanonicalMarketBarStoreV2().load_instrument_range" in page
    assert 'run_every="60s"' in page
    assert "confirmed_turns_v1" in research
    assert "HT_DCPERIOD" in page  # Clearly states NOT exact Ehlers.
    for forbidden in (
        "SaxoOrderRequest", "place_order(", "set_live_enabled",
        "save_autotrader_config_v3", "reserve_order_v3",
        "INSERT INTO ", "DELETE FROM ", "UPDATE autotrader",
    ):
        assert forbidden not in page+research
