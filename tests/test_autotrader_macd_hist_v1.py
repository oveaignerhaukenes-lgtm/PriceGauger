from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from autotrader_macd_hist_v1 import histogram_turn_v1
from autotrader_macd_timeframe_live_v1 import _timeframe_clock_v1
from autotrader_family_replay_v1 import replay_strategy_family_v1
from autotrader_strategy_family_v1 import (
    FAMILY_MACD_HIST_STRATEGY_V1,
    FAMILY_MACD_HIST_V1,
    family_strategy_key_v1,
)


START = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)


def observations(*spreads, gap=False):
    return tuple(
        SimpleNamespace(
            spread=float(spread), macd=float(spread), signal=0.0,
            closed_at=START + timedelta(minutes=15 * (index + (1 if gap and index == 2 else 0))),
        )
        for index, spread in enumerate(spreads)
    )


def test_histogram_turn_is_two_strict_closed_movements_and_ignores_zero():
    assert histogram_turn_v1(observations(-8, -6, -4), timeframe_minutes=15) == "LONG"
    assert histogram_turn_v1(observations(8, 6, 4), timeframe_minutes=15) == "SHORT"
    assert histogram_turn_v1(observations(-2, 1, 3), timeframe_minutes=15) == "LONG"
    assert histogram_turn_v1(observations(3, 1, -2), timeframe_minutes=15) == "SHORT"
    assert histogram_turn_v1(observations(-8, -6), timeframe_minutes=15) is None
    assert histogram_turn_v1(observations(-8, -6, -6), timeframe_minutes=15) is None
    assert histogram_turn_v1(observations(-8, -5, -7), timeframe_minutes=15) is None
    assert histogram_turn_v1(observations(-8, -6, -4, gap=True), timeframe_minutes=15) is None


def test_live_clock_uses_same_histogram_rule_and_preserves_old_cross():
    bars = (SimpleNamespace(point=(START.isoformat(), 100.0), market_name="NAS"),)
    with patch("autotrader_macd_timeframe_live_v1.closed_bars_v2", return_value=(object(),)), patch(
        "autotrader_macd_timeframe_live_v1.macd_observations_v2", return_value=observations(-8, -6, -4)
    ):
        hist = _timeframe_clock_v1(bars, timeframe_minutes=15, histogram_turn=True)
        zero_cross = _timeframe_clock_v1(bars, timeframe_minutes=15)
    assert hist.cross_direction == "LONG"
    assert zero_cross.cross_direction is None
    assert hist.action_at == START + timedelta(minutes=30)


def test_new_family_has_separate_strategy_key():
    assert family_strategy_key_v1(FAMILY_MACD_HIST_V1) == FAMILY_MACD_HIST_STRATEGY_V1


def test_simulation_changes_only_at_closed_histogram_turn():
    bars = tuple(
        SimpleNamespace(
            bar_time=START + timedelta(minutes=index), close=100 + index,
            point=((START + timedelta(minutes=index)).isoformat(), 100 + index),
            market_name="NAS",
        )
        for index in range(46)
    )
    with patch("autotrader_family_replay_v1.closed_bars_v2", return_value=(object(),)), patch(
        "autotrader_family_replay_v1.macd_observations_v2",
        return_value=observations(-8, -6, -4),
    ):
        replay = replay_strategy_family_v1(bars, family=FAMILY_MACD_HIST_V1, timeframe_minutes=15)
    assert replay.loc[START + timedelta(minutes=29), "TARGET"] == 0
    assert replay.loc[START + timedelta(minutes=30), "TARGET"] == 1
