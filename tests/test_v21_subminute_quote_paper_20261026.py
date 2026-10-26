"""30s / 15s BBO bar construction and safe PAPER flip simulation."""
from datetime import datetime, timedelta, timezone
from math import sin
from types import SimpleNamespace

import pytest

from macd_stoch_v21_30s_research_v1 import (
    MAX_QUOTES, Quote30V1, PaperResult30V1,
    _hypothetical_target, build_completed_bars_v1,
    run_v21_quote_paper_v1, validate_quotes_v1,
)

START = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)


def quote_stream(n=4250, *, gap_at=None):
    result = []
    for t in range(n):
        if gap_at is not None and gap_at <= t < gap_at + 35:
            continue
        at = START + timedelta(seconds=t)
        mid = 20000. + 45 * sin(t / 180) + 8 * sin(t / 35)
        result.append({
            "quote_at": at.isoformat(),
            "received_at": (at + timedelta(milliseconds=220)).isoformat(),
            "bid": mid - 1.1,
            "ask": mid + 1.1,
        })
    return result


def test_15_30_60_are_genuine_completed_bbo_bars():
    quotes = validate_quotes_v1(quote_stream(120))
    for interval, total in ((15, 8), (30, 4), (60, 2)):
        formed = build_completed_bars_v1(
            quotes, interval_seconds=interval, market="Tech100",
            observed_through=START + timedelta(seconds=120),
        )
        assert len(formed) == total
        assert all(item.samples == interval for item in formed)
        assert formed[0].bar.open == pytest.approx(quotes[0].mid)
        assert formed[0].bar.close == pytest.approx(quotes[interval - 1].mid)
        assert formed[0].closed_at == START + timedelta(seconds=interval)
    only_completed = build_completed_bars_v1(
        quotes, interval_seconds=60, market="Tech100",
        observed_through=START + timedelta(seconds=75)
    )
    assert len(only_completed) == 1


def test_gap_does_not_become_fabricated_candle():
    quotes = validate_quotes_v1(quote_stream(180, gap_at=70))
    items = build_completed_bars_v1(
        quotes, interval_seconds=15, market="Tech100",
        observed_through=START + timedelta(seconds=180),
    )
    assert len(items) < 12
    assert not any(
        START + timedelta(seconds=75) <= row.closed_at
        <= START + timedelta(seconds=105) for row in items
    )


@pytest.mark.parametrize("seconds", (15, 30, 60))
@pytest.mark.parametrize("mode", ("flat_first", "direct_1bar"))
def test_paper_scenarios_no_orders_and_bounded(seconds, mode):
    quotes = validate_quotes_v1(quote_stream())
    t = run_v21_quote_paper_v1(
        quotes, seconds=seconds, reversal_mode=mode,
        observed_through=START + timedelta(seconds=4250),
        hypothetical_latency_seconds=1,
    )
    assert isinstance(t, PaperResult30V1)
    assert t.total_quotes == 4250
    assert t.interval_seconds == seconds
    assert t.modeled_bars > 0
    assert t.reversal_mode == mode
    assert t.hypothetical_latency_seconds == 1
    assert t.incomplete_segments >= 0
    if t.incomplete_segments:
        assert t.hypothetical_pnl_points_lots is None
    for a in t.actions:
        dt = datetime.fromisoformat(a.at)
        bar = datetime.fromisoformat(a.closed_bar)
        assert dt >= bar + timedelta(seconds=seconds + 1)
        assert a.bid <= a.price <= a.ask


def test_direct_flip_uses_exact_net_position_no_intermediate_double_exposure():
    d = SimpleNamespace(
        action="OPPOSITE_FLAT", target=SimpleNamespace(amount=0.),
        composite_score=.65,
    )
    target, action = _hypothetical_target(
        d, -.02, reversal_mode="direct_1bar", tranche=.01,
    )
    assert target == pytest.approx(.01)
    assert action == "DIRECT_NET_FLIP_1BAR_PAPER"
    target, action = _hypothetical_target(
        d, -.02, reversal_mode="flat_first", tranche=.01,
    )
    assert target == 0. and action == "OPPOSITE_FLAT"
    weak = SimpleNamespace(action="OPPOSITE_FLAT",
                           target=SimpleNamespace(amount=0.),
                           composite_score=.12)
    assert _hypothetical_target(
        weak, -.02, reversal_mode="direct_1bar", tranche=.01
    ) == (0., "OPPOSITE_FLAT")


def test_quote_validation_prevents_duplicate_out_of_order_and_stale_sources():
    raw = quote_stream(100)
    with pytest.raises(ValueError, match="duplicate|unordered"):
        validate_quotes_v1(raw + [raw[-1]])
    stale = dict(raw[2])
    stale["received_at"] = (
        START + timedelta(seconds=40)
    ).isoformat()
    with pytest.raises(ValueError, match="delayed"):
        validate_quotes_v1(raw[:2] + [stale] + raw[3:])
    with pytest.raises(ValueError, match="fixed bound"):
        validate_quotes_v1([raw[0]] * (MAX_QUOTES + 1))


def test_bad_flip_mode_and_latency_rejected_without_live_execution():
    quotes = validate_quotes_v1(quote_stream(10))
    with pytest.raises(ValueError):
        run_v21_quote_paper_v1(
            quotes, seconds=15, observed_through=START,
            reversal_mode="no_controls"
        )
    with pytest.raises(ValueError):
        run_v21_quote_paper_v1(
            quotes, seconds=15, observed_through=START,
            hypothetical_latency_seconds=100
        )


def test_prefix_quotes_cannot_be_changed_by_later_appends():
    initial = validate_quotes_v1(quote_stream(4000))
    extended = validate_quotes_v1(quote_stream(4250))
    cutoff = START + timedelta(seconds=3900)
    a = build_completed_bars_v1(initial, interval_seconds=15,
                               market="Tech100", observed_through=cutoff)
    b = build_completed_bars_v1(extended, interval_seconds=15,
                               market="Tech100", observed_through=cutoff)
    assert a == b
