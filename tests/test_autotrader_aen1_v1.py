from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from autotrader_aen1_v1 import Aen1
from autotrader_aen1_series_v1 import replay_aen1_series_v1


START = datetime(2026, 9, 25, 15, 0, tzinfo=timezone.utc)


def feed(model, index, price):
    return model.on_close(START + timedelta(minutes=index), price)


def test_breakout_trailing_exit_and_cooldown_without_direct_reversal():
    model = Aen1()
    for minute in range(61):
        feed(model, minute, 100 + minute * 0.05)
    entry = feed(model, 61, 116)
    assert entry is not None and entry.target == "LONG"
    assert feed(model, 62, 120) is None
    exit_signal = feed(model, 63, 115)
    assert exit_signal is not None and exit_signal.target == "FLAT"
    assert feed(model, 64, 102) is None
    assert model.state == "FLAT"


def test_back_and_forth_prices_do_not_trigger_a_breakout():
    model = Aen1()
    decisions = [feed(model, i, 100 + (2 if i % 2 else -2)) for i in range(90)]
    assert all(item is None for item in decisions)


def test_missing_minute_flattens_and_clears_warmup():
    model = Aen1()
    for i in range(61):
        feed(model, i, 100 + i * 0.05)
    assert feed(model, 61, 116).target == "LONG"
    gap = feed(model, 64, 118)
    assert gap is not None and gap.reason == "DATA_GAP" and gap.target == "FLAT"
    assert feed(model, 65, 150) is None


def test_shadow_charges_entry_and_exit_at_the_decision_close():
    closes = [100 + i * 0.05 for i in range(62)] + [116, 120, 115]
    bars = [SimpleNamespace(bar_time=START + timedelta(minutes=i), close=value)
            for i, value in enumerate(closes)]
    result = replay_aen1_series_v1(
        bars, seed_equity=1000, currency="NOK",
        started_at=START, as_of=START + timedelta(minutes=len(bars)),
    )
    assert result is not None
    entry = next(i for i, point in enumerate(result.points) if point.position_state == "LONG")
    assert result.points[entry].equity < 1000  # One half-spread, no same-bar gain.
    assert result.points[entry + 1].equity > result.points[entry].equity
    assert result.points[-1].position_state == "FLAT"
