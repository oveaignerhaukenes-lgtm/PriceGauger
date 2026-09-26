from datetime import datetime, timedelta, timezone

from autotrader_hunter_v1 import Hunter, HunterConfig


T0 = datetime(2026, 9, 25, 16, 0, tzinfo=timezone.utc)


def send(model, second, price, spread=1.0):
    return model.on_quote(T0 + timedelta(seconds=second), price - spread / 2, price + spread / 2)


def test_impulse_exhaustion_and_shallow_new_high_without_reversal():
    h = Hunter(HunterConfig(minimum_impulse_points=8, exhaustion_seconds=2, cooldown_seconds=1))
    assert send(h, 0, 100) is None
    assert send(h, 1, 110).target == "LONG"
    assert send(h, 2, 120) is None
    assert send(h, 3, 119) is None
    exit_signal = send(h, 4, 118)
    assert exit_signal.target == "FLAT" and exit_signal.reason == "IMPULSE_EXHAUSTED"
    assert send(h, 5, 118) is None
    assert send(h, 6, 120.5) is None  # New HH must clear the spread, too.
    continuation = send(h, 7, 121.1)
    assert continuation.target == "LONG" and continuation.reason == "SHALLOW_PULLBACK_NEW_EXTREME"


def test_deep_pullback_cancels_continuation_and_needs_new_impulse():
    h = Hunter(HunterConfig(exhaustion_seconds=1, cooldown_seconds=1))
    send(h, 0, 100)
    send(h, 1, 110)
    send(h, 2, 120)
    assert send(h, 3, 117).target == "FLAT"
    assert send(h, 4, 115) is None
    assert send(h, 5, 121) is None  # Prior HH no longer grants re-entry.


def test_short_impulse_and_stale_quote_do_not_create_extra_transitions():
    h = Hunter()
    send(h, 0, 100)
    assert send(h, 1, 90).target == "SHORT"
    assert send(h, 1, 140) is None
    assert h.target == "SHORT"
    assert send(h, 7, 80) is None  # Gap does not imply a broker fill.
    assert h.target == "SHORT"


def test_spread_gate_prevents_entry():
    h = Hunter()
    send(h, 0, 100)
    assert send(h, 1, 120, spread=6) is None
    assert h.target == "FLAT"
