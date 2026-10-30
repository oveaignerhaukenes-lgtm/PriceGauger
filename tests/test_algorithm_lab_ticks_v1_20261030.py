"""Real Saxo quote replay contracts: no lookahead, next quote fill, side limits."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from algorithm_lab_v1 import LabCosts, PRESETS
from algorithm_lab_ticks_v1 import replay_tick_impulses

START = datetime(2026, 10, 1, tzinfo=timezone.utc)
COSTS = LabCosts(point_value_nok=100., lot_size=.01, starting_nav_nok=10000.,
                 spread_bps=50., slippage_bps=0., commission_nok=0.)


def quotes(n=90, *, direction=1, spread=.2, gap_at=None):
    result = []
    for i in range(n):
        t = START + timedelta(seconds=i+(12 if gap_at is not None and i >= gap_at else 0))
        mid = 10000. + direction * i
        result.append({"quote_at": t, "bid": mid-spread/2, "ask": mid+spread/2})
    return result


def run(*, side="long", candles=None, start=START, end=None, spread=.2,
        max_hold=60, entry_bps=8.):
    base = dict(PRESETS["Impulse Up Collector" if side == "long" else
                        "Impulse Down Collector"])
    base.update(lookback=10, max_hold=max_hold, entry_bps=entry_bps,
                fade_bps=1.)
    return replay_tick_impulses(
        plan=base, quotes=candles or quotes(spread=spread,
                                          direction=1 if side == "long" else -1),
        costs=COSTS, start_at=start,
        end_at=end or START+timedelta(seconds=95))


def test_long_entry_after_observed_signal_and_never_short():
    r = run()
    first = next(t for t in r.trades if t.action == "OPEN")
    assert first.at >= START+timedelta(seconds=11)
    assert all(t.after >= 0 for t in r.trades)
    assert r.pnl_nok > 0
    assert r.points[-1].position == 0


def test_short_entry_and_flat_only():
    r = run(side="short")
    assert any(t.action == "OPEN" for t in r.trades)
    assert all(t.after <= 0 for t in r.trades)


def test_quote_gap_cannot_be_filled_with_future_price():
    r = run(candles=quotes(gap_at=30), max_hold=200,
            end=START+timedelta(seconds=120))
    assert r.gaps == 1
    assert any(t.action == "GAP_FLAT" for t in r.trades)


def test_lookback_not_estimated_from_incomplete_quote_history():
    r = run(candles=quotes(5), end=START+timedelta(seconds=6))
    assert not r.trades
    assert r.pnl_nok == 0


def test_actual_historical_spread_increases_costs():
    narrow = run(candles=quotes(spread=.2))
    wide = run(candles=quotes(spread=10.))
    assert wide.total_cost_nok > narrow.total_cost_nok
    assert wide.pnl_nok < narrow.pnl_nok


def test_quote_time_and_schema_are_strict():
    invalid = quotes(4)
    invalid[2]["bid"] = invalid[2]["ask"] + 1.
    with pytest.raises(ValueError):
        run(candles=invalid)
    duplicate = quotes(4)
    duplicate[2]["quote_at"] = duplicate[1]["quote_at"]
    with pytest.raises(ValueError):
        run(candles=duplicate)


def test_regime_cannot_be_silently_ignored_in_tick_engine():
    plan = dict(PRESETS["Impulse Up Collector"])
    plan["regime_rule"] = "spread"
    with pytest.raises(ValueError, match="Regimefiltrert"):
        replay_tick_impulses(plan=plan, quotes=quotes(), costs=COSTS,
                             start_at=START, end_at=START+timedelta(seconds=95))
