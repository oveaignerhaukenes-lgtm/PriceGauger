from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from autotrader_market_rhythm_v1 import confirmed_turns_v1, market_rhythm_profile_v1


def _prices(values, *, start="2026-10-16T08:00:00Z"):
    return pd.Series(
        values,
        index=pd.date_range(start, periods=len(values), freq="1min", tz="UTC"),
        dtype=float,
    )


def test_turning_point_is_known_only_after_opposing_move():
    price = _prices([100.0, 101.0, 100.0, 99.0, 100.0, 101.0, 100.0])
    a = confirmed_turns_v1(price.iloc[:2], reversal_pct=0.5)
    assert len(a) == 1
    assert a[0].kind == "TROUGH"
    assert a[0].pivot_at == price.index[0]
    assert a[0].confirmed_at == price.index[1]

    b = confirmed_turns_v1(price.iloc[:3], reversal_pct=0.5)
    assert len(b) == 2
    assert b[1].kind == "PEAK"
    assert b[1].pivot_at == price.index[1]
    assert b[1].confirmed_at == price.index[2]
    # Adding future candles never revises an already confirmed turn.
    assert tuple(confirmed_turns_v1(price, reversal_pct=0.5)[:2]) == b


def test_detects_four_minute_full_cycles_and_two_minute_legs():
    wave = _prices([100.0, 101.0, 100.0, 99.0] * 15)
    result = market_rhythm_profile_v1(wave, window="60m", thresholds_pct=(0.5, 3.0))
    medium, large = result
    assert medium.completed_cycles >= 8
    assert medium.median_leg_minutes == pytest.approx(2.0)
    assert medium.median_cycle_minutes == pytest.approx(4.0)
    assert medium.cycle_period_cv is not None
    assert medium.cycle_period_cv < 0.2
    assert medium.median_leg_amplitude_pct > 1.5
    assert medium.leg_duration_2m > 0
    assert large.completed_cycles == 0
    assert large.median_cycle_minutes is None


def test_small_noisy_cycles_are_not_large_threshold_cycles():
    prices = _prices([100.0, 100.35, 100.0, 99.65] * 20)
    small, huge = market_rhythm_profile_v1(prices, window="80m", thresholds_pct=(0.25, 1.0))
    assert small.completed_cycles >= 8
    assert huge.completed_cycles == 0


def test_missing_one_minute_is_not_fabricated_into_a_fast_leg():
    p = _prices([100.0, 101.0, 100.0, 99.0, 100.0, 101.0])
    shifted = p.copy()
    shifted.index = pd.DatetimeIndex([
        p.index[0], p.index[1], p.index[2],
        p.index[3] + pd.Timedelta(minutes=8),
        p.index[4] + pd.Timedelta(minutes=8),
        p.index[5] + pd.Timedelta(minutes=8),
    ])
    turns = confirmed_turns_v1(shifted, reversal_pct=0.5)
    assert len({x.segment for x in turns}) == 2
    metric = market_rhythm_profile_v1(shifted, window="gap", thresholds_pct=(0.5,))[0]
    assert metric.completed_cycles == 0
    assert metric.completed_legs <= 2


def test_no_completed_cycles_does_not_claim_market_has_zero_period():
    monotonic = _prices([100 + 0.01 * i for i in range(100)])
    metric = market_rhythm_profile_v1(monotonic, window="trend", thresholds_pct=(0.05,))[0]
    assert metric.completed_cycles == 0
    assert metric.median_cycle_minutes is None
    assert metric.cycle_period_cv is None


def test_invalid_threshold_and_prices_fail_closed():
    price = _prices([100.0, 101.0, 100.0])
    with pytest.raises(ValueError):
        confirmed_turns_v1(price, reversal_pct=0)
    with pytest.raises(ValueError):
        confirmed_turns_v1(price, reversal_pct=100)
    with pytest.raises(ValueError):
        confirmed_turns_v1(pd.Series([100.0, 99.0]), reversal_pct=0.5)


def test_tradingdesk_rhythm_panel_is_paper_only():
    panel = Path("tradingdesk_strategy_scoreboard_v1.py").read_text(encoding="utf-8")
    assert "market_rhythm_profile_v1" in panel
    assert "Rytmeprofil" in panel
    assert "matched" not in panel.lower() or "LIVE" in panel
    assert "set_live_enabled_v3" not in panel
    assert "place_order(" not in panel
