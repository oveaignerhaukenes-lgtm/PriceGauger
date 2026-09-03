from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from autotrader_shadow_benchmark_v2 import ShadowBenchmarkSeriesV2, ShadowEquityPointV2
from autotrader_shadow_leverage_v2 import (
    LiveLeveragePointV2,
    LiveLeverageScheduleV2,
    apply_live_equivalent_leverage_v2,
    leverage_at_v2,
)


START = datetime(2026, 9, 3, 10, 0, tzinfo=timezone.utc)


def _series() -> ShadowBenchmarkSeriesV2:
    return ShadowBenchmarkSeriesV2(
        strategy_key="control",
        execution_mode="SHADOW_CONTROL",
        currency="NOK",
        seed_equity=500.0,
        started_at=START,
        points=(
            ShadowEquityPointV2(START, 500.0, "LONG"),
            ShadowEquityPointV2(START + timedelta(minutes=1), 505.0, "LONG"),
            ShadowEquityPointV2(START + timedelta(minutes=2), 499.95, "SHORT"),
        ),
    )


def test_leverage_schedule_uses_fallback_before_first_observed_open():
    schedule = LiveLeverageScheduleV2(
        points=(LiveLeveragePointV2(START + timedelta(minutes=2), 20.0, "SAXO_OPEN_PRECHECK"),),
        fallback_leverage=15.0,
        source="PILOT_MARGIN_CONFIG",
    )

    assert leverage_at_v2(schedule, START) == pytest.approx(15.0)
    assert leverage_at_v2(schedule, START + timedelta(minutes=3)) == pytest.approx(20.0)


def test_shadow_returns_are_scaled_to_effective_live_exposure_without_changing_state():
    schedule = LiveLeverageScheduleV2(points=(), fallback_leverage=10.0, source="TEST")

    result = apply_live_equivalent_leverage_v2(_series(), schedule=schedule)

    # +1% then -1% at 1x becomes +10% then -10% at 10x.
    assert result.points[1].equity == pytest.approx(550.0)
    assert result.points[2].equity == pytest.approx(495.0)
    assert [point.position_state for point in result.points] == ["LONG", "LONG", "SHORT"]
    assert result.strategy_key == "control"
