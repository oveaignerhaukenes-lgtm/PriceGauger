from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import autotrader_macd_timeframe_live_v1 as runtime


def test_live_macd_warmup_spans_weekends_and_holidays() -> None:
    assert runtime.MACD_WARMUP_LOOKBACK_V1 >= timedelta(days=7)
    assert runtime.MACD_WARMUP_MAX_BARS_V1 >= 10_000


def test_wider_warmup_does_not_remove_gap_transition_guard() -> None:
    source = Path("autotrader_macd_timeframe_live_v1.py").read_text(encoding="utf-8")
    assert "start=end - MACD_WARMUP_LOOKBACK_V1" in source
    assert "limit=MACD_WARMUP_MAX_BARS_V1" in source
    assert "data_gap = current.closed_at - previous.closed_at != expected" in source
    assert "if not data_gap:" in source
    assert "elif clock.data_gap:" in source
    assert 'reason = f"DATA_GAP_{minutes}M_HOLD"' in source
