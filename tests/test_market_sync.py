from datetime import datetime, timezone

import pandas as pd
import pytest

from market_sync import synchronize_market_frames


def _frame(timestamps: list[str]) -> pd.DataFrame:
    values = list(range(1, len(timestamps) + 1))
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": values,
            "high": [value + 0.5 for value in values],
            "low": [value - 0.5 for value in values],
            "close": values,
            "volume": [100] * len(values),
        }
    )


def test_synchronizes_all_frames_to_slowest_completed_bar() -> None:
    frames = {
        "5m": _frame(["2026-07-24T09:50:00Z", "2026-07-24T09:55:00Z", "2026-07-24T10:00:00Z"]),
        "30m": _frame(["2026-07-24T09:00:00Z", "2026-07-24T09:30:00Z", "2026-07-24T10:00:00Z"]),
        "1h": _frame(["2026-07-24T08:00:00Z", "2026-07-24T09:00:00Z"]),
    }

    result = synchronize_market_frames(
        frames,
        received_at=datetime(2026, 7, 24, 10, 20, tzinfo=timezone.utc),
    )

    assert result.cutoff == pd.Timestamp("2026-07-24T10:00:00Z")
    assert result.lag_minutes == pytest.approx(20.0)
    assert result.mode == "SYNCHRONIZED_SIM"

    assert result.frames["5m"]["timestamp"].tolist() == [
        pd.Timestamp("2026-07-24T09:50:00Z"),
        pd.Timestamp("2026-07-24T09:55:00Z"),
    ]
    assert result.frames["30m"]["timestamp"].tolist() == [
        pd.Timestamp("2026-07-24T09:00:00Z"),
        pd.Timestamp("2026-07-24T09:30:00Z"),
    ]
    assert result.frames["1h"]["timestamp"].tolist() == [
        pd.Timestamp("2026-07-24T08:00:00Z"),
        pd.Timestamp("2026-07-24T09:00:00Z"),
    ]


def test_rejects_missing_required_stream_data() -> None:
    with pytest.raises(ValueError, match="5m har ingen markedsdata"):
        synchronize_market_frames({"5m": pd.DataFrame()})


def test_rejects_unknown_timeframe() -> None:
    with pytest.raises(ValueError, match="Ukjent tidsramme"):
        synchronize_market_frames({"2h": _frame(["2026-07-24T08:00:00Z"])})
