"""Causal tests for standalone 1m Probability Lab, no Saxo/database calls."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from probability_lab_v1 import (
    skellam_proxy, score_forecasts, up_calibration, walk_forward_probability,
)


START = datetime(2026, 10, 20, 8, tzinfo=timezone.utc)


def make_bars(count=260, *, gap_at=None, replace_at=None, replacement=0.):
    bars = []
    price = 20000.
    for i in range(count):
        # Persistent sign bouts with occasional reversals, not coin-flip iid.
        change = (3. if (i // 12) % 2 == 0 else -2.) + (i % 7) * .02
        price += change
        stamp = START + timedelta(minutes=i + (15 if gap_at is not None and i >= gap_at else 0))
        px = replacement if i == replace_at else price
        bars.append(SimpleNamespace(
            bar_time=stamp.isoformat(), close=px, open=px - .5,
            high=px + .5, low=px - .5,
        ))
    return bars


def test_skellam_distribution_sign_and_symmetry():
    up, down, flat = skellam_proxy(.65, .20, 5)
    assert up > down > 0.
    assert 0 < flat < 1
    assert up + down + flat == pytest.approx(1.)
    a, b, _ = skellam_proxy(.35, .35, 1)
    assert a == pytest.approx(b)
    assert skellam_proxy(0., 0., 1) == pytest.approx((0., 0., 1.))


@pytest.mark.parametrize("h", (1, 2, 5, 10))
def test_probabilities_sum_to_one_and_labeled_target_is_correct(h):
    bars = make_bars()
    forecasts, preview, gaps = walk_forward_probability(
        bars, horizon=h, lag=2, window=120,
    )
    assert len(forecasts) >= 180
    assert gaps == 0
    assert preview is not None and preview.actual is None
    assert preview.target is None
    assert forecasts[0].horizon == h
    for f in forecasts:
        for model in ("baseline", "markov", "skellam"):
            p = getattr(f, model)
            assert sum(p) == pytest.approx(1., abs=1e-10)
            assert all(0 <= v <= 1 for v in p)
        assert f.actual in ("up", "down", "flat")
    score = score_forecasts(forecasts, "markov", threshold=.55, roundtrip_bps=8)
    assert score["n"] == len(forecasts)
    assert 0 <= score["brier"] <= 2.
    assert sum(row["n"] for row in up_calibration(forecasts, "markov")) == len(forecasts)


def test_appending_future_does_not_change_existing_probabilities():
    first, _, _ = walk_forward_probability(make_bars(200), horizon=5, lag=3)
    extended, _, _ = walk_forward_probability(make_bars(260), horizon=5, lag=3)
    first_by_time = {f.asof: f for f in first}
    extended_by_time = {f.asof: f for f in extended}
    for at, row in first_by_time.items():
        current = extended_by_time[at]
        assert row.markov == current.markov
        assert row.baseline == current.baseline
        assert row.skellam == current.skellam
        assert row.actual == current.actual


def test_future_target_change_cannot_affect_earlier_prediction():
    old, _, _ = walk_forward_probability(make_bars(180), horizon=1, lag=2)
    changed, _, _ = walk_forward_probability(
        make_bars(180, replace_at=179, replacement=25000.), horizon=1, lag=2
    )
    assert old[-1].asof == changed[-1].asof
    assert old[-1].markov == changed[-1].markov
    assert old[-1].skellam == changed[-1].skellam
    assert old[-1].actual != changed[-1].actual


def test_breaks_never_bridge_missing_one_minute_bars():
    items, preview, gaps = walk_forward_probability(
        make_bars(310, gap_at=140), horizon=10, lag=2
    )
    assert gaps == 1
    assert len(items) > 100
    assert preview is not None
    for f in items:
        start = datetime.fromisoformat(f.asof)
        target = datetime.fromisoformat(f.target)
        assert target - start == timedelta(minutes=10)


def test_input_rejects_bad_times_and_nonpositive_quotes():
    with pytest.raises(ValueError, match="sorted and unique"):
        walk_forward_probability(make_bars(80) + [make_bars(80)[-1]])
    with pytest.raises(ValueError, match="invalid 1m close"):
        walk_forward_probability(make_bars(80, replace_at=40, replacement=0))


def test_no_fabricated_trading_result_and_cost_penalty():
    predictions, _, _ = walk_forward_probability(make_bars(260), lag=1)
    no_cost = score_forecasts(predictions, "markov", threshold=.35, roundtrip_bps=0)
    cost = score_forecasts(predictions, "markov", threshold=.35, roundtrip_bps=10)
    assert no_cost["signals"] == cost["signals"] > 0
    assert cost["mean_signal_net_pct"] == pytest.approx(
        no_cost["mean_signal_net_pct"] - .10
    )
