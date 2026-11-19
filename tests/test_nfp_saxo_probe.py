import pandas as pd
from nfp_saxo_probe import reaction, collect


def test_reaction_uses_completed_minute_and_next_open():
    release = pd.Timestamp("2026-10-02T12:30:00Z")
    times = pd.date_range(release - pd.Timedelta(minutes=1), periods=32, freq="min")
    closes = [100.0] + [101.0] * 31
    frame = pd.DataFrame({"timestamp": times, "close": closes, "open": [100.0, 101.0, 102.0] + [101.0] * 29})
    result = reaction(frame, release)
    assert result["m1"] == 1.0
    assert result["entry_open"] == 102.0
    assert result["m30"] == 1.0


def test_missing_baseline_is_explicit():
    release = pd.Timestamp("2026-10-02T12:30:00Z")
    frame = pd.DataFrame({"timestamp": [release], "close": [101.0]})
    assert reaction(frame, release)["status"] == "MISSING_BASELINE"


def test_missing_later_bars_not_interpolated():
    release = pd.Timestamp("2026-10-02T12:30:00Z")
    frame = pd.DataFrame({
        "timestamp": [release - pd.Timedelta(minutes=1), release, release + pd.Timedelta(minutes=1)],
        "open": [100.0, 100.0, 101.0],
        "close": [100.0, 101.0, 102.0],
    })
    result = reaction(frame, release)
    assert result["m1"] == 1.0
    assert result["m5"] is None
    assert result["entry_open"] == 101.0
