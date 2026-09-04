from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math

import autotrader_macd_timeframe_controls_v1 as controls
from autotrader_pnl_chart_v2 import _strategy_label
from autotrader_shadow_benchmark_v2 import STATE_FLAT
from autotrader_strategy_catalog_v2 import AUTOTRADER_STRATEGIES_V2
from autotrader_strategy_series_materializer_v1 import strategy_series_version_v1
from canonical_market_bars_v2 import CanonicalMarketBarV2


def _bars(count: int = 2400) -> tuple[CanonicalMarketBarV2, ...]:
    start = datetime(2026, 9, 1, 0, 0, tzinfo=timezone.utc)
    result = []
    for index in range(count):
        stamp = start + timedelta(minutes=index)
        price = 100.0 + 2.4 * math.sin(index / 21.0) + 0.0015 * index
        result.append(
            CanonicalMarketBarV2(
                instrument_id=1,
                market_id=1,
                market_name="Synthetic",
                bar_time=stamp.isoformat(),
                open=price,
                high=price,
                low=price,
                close=price,
                volume=None,
                quality_flags=1,
            )
        )
    return tuple(result)


def test_requested_timeframes_are_exactly_the_new_baseline_set() -> None:
    assert controls.MACD_CONTROL_TIMEFRAMES_MINUTES_V1 == (2, 5, 10, 15, 20)
    assert tuple(controls.MACD_CONTROL_STRATEGY_KEYS_V1) == (2, 5, 10, 15, 20)


def test_each_timeframe_builds_a_closed_bar_macd_flip_control() -> None:
    bars = _bars()
    started = datetime(2026, 9, 1, 14, 0, tzinfo=timezone.utc)
    end = datetime(2026, 9, 2, 15, 59, tzinfo=timezone.utc)

    for minutes in controls.MACD_CONTROL_TIMEFRAMES_MINUTES_V1:
        crosses = controls._crosses_by_action_v1(bars, timeframe_minutes=minutes)
        assert crosses, f"expected synthetic {minutes}m MACD crosses"
        series = controls._series_for_timeframe_v1(
            bars,
            timeframe_minutes=minutes,
            seed_equity=500.0,
            currency="NOK",
            started_at=started,
            as_of=end,
        )
        assert series is not None
        assert series.strategy_key == controls.macd_control_strategy_key_v1(minutes)
        assert series.execution_mode == "SHADOW_CONTROL"
        assert series.points[0].position_state == STATE_FLAT
        assert any(point.position_state != STATE_FLAT for point in series.points[1:])


def test_timeframe_controls_have_readable_labels_and_only_2m_15m_are_live() -> None:
    live_keys = {item.key for item in AUTOTRADER_STRATEGIES_V2}
    for minutes, key in controls.MACD_CONTROL_STRATEGY_KEYS_V1.items():
        if minutes in {2, 15}:
            assert key in live_keys
        else:
            assert key not in live_keys
        assert _strategy_label(key) == f"{minutes}m MACD flip · control"
        assert strategy_series_version_v1(key) == controls.SERIES_VERSION_V1
