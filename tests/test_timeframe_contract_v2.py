from __future__ import annotations

import pandas as pd

from timeframe_contract_v2 import (
    build_runtime_frames_from_canonical_1m_v2,
    normalize_canonical_1m_v2,
)


def test_normalization_is_utc_sorted_and_last_duplicate_wins():
    frame = normalize_canonical_1m_v2(
        [
            ("2026-08-14T12:01:00+02:00", 101.0),
            ("2026-08-14T10:00:00Z", 100.0),
            ("2026-08-14T10:01:00Z", 102.0),
        ]
    )

    assert list(frame["timestamp"]) == [
        pd.Timestamp("2026-08-14T10:00:00Z"),
        pd.Timestamp("2026-08-14T10:01:00Z"),
    ]
    assert list(frame["close"]) == [100.0, 102.0]


def test_live_bucket_uses_latest_real_observation_without_forward_fill():
    frames = build_runtime_frames_from_canonical_1m_v2(
        [
            ("2026-08-14T10:00:00Z", 100.0),
            ("2026-08-14T10:01:00Z", 101.0),
            # 10:02 and 10:03 are deliberately absent.
            ("2026-08-14T10:04:00Z", 104.0),
            ("2026-08-14T10:05:00Z", 105.0),
            ("2026-08-14T10:06:00Z", 106.0),
        ],
        timeframes={"5m": "5min"},
    )

    five = frames["5m"]
    assert len(five) == 2
    assert five.iloc[0]["open"] == 100.0
    assert five.iloc[0]["close"] == 104.0
    assert five.iloc[1]["open"] == 105.0
    assert five.iloc[1]["close"] == 106.0
    # Five real minute observations were supplied; the two missing minutes were
    # not synthesized, so canonical 1m retains exactly those five observations.
    assert frames["1m"].shape[0] == 5


def test_timeframe_buckets_are_utc_epoch_aligned():
    frames = build_runtime_frames_from_canonical_1m_v2(
        [
            ("2026-08-14T10:14:00Z", 100.0),
            ("2026-08-14T10:15:00Z", 101.0),
            ("2026-08-14T10:29:00Z", 102.0),
            ("2026-08-14T10:30:00Z", 103.0),
        ],
        timeframes={"15m": "15min", "30m": "30min"},
    )

    assert list(frames["15m"]["timestamp"]) == [
        pd.Timestamp("2026-08-14T10:00:00Z"),
        pd.Timestamp("2026-08-14T10:15:00Z"),
        pd.Timestamp("2026-08-14T10:30:00Z"),
    ]
    assert list(frames["30m"]["timestamp"]) == [
        pd.Timestamp("2026-08-14T10:00:00Z"),
        pd.Timestamp("2026-08-14T10:30:00Z"),
    ]


def test_active_higher_timeframe_close_matches_latest_canonical_observation():
    frames = build_runtime_frames_from_canonical_1m_v2(
        [
            ("2026-08-14T10:00:00Z", 100.0),
            ("2026-08-14T10:31:00Z", 111.0),
        ],
        timeframes={"30m": "30min", "1h": "1h", "4h": "4h"},
    )

    for name in ("30m", "1h", "4h"):
        assert frames[name].iloc[-1]["close"] == 111.0
