from datetime import datetime, timezone

from autotrader_macd_a_extended_v1 import select_extended_macd_a
from autotrader_macd_a_pyr_v1 import Cross, PyramidState, plan_macd_a_pyramid
from autotrader_strategy_catalog_v2 import strategy_spec_v2


def test_extended_preserves_fast_direction_and_reports_slow_alignment():
    result = select_extended_macd_a({1: 1, 2: -1, 5: -1, 15: 1, 30: 1}, micro_edge=.8, noise=.2)
    assert (result.direction, result.selected_minutes, result.regime) == ("LONG", 1, "STRONG_ALIGNMENT")
    assert result.confirmed_minutes == (1, 15, 30)


def test_opposite_slow_regime_never_overrides_adaptive_direction():
    result = select_extended_macd_a({1: 1, 2: 1, 5: -1, 15: -1, 30: -1}, micro_edge=.8, noise=.2)
    assert result.direction == "LONG"
    assert result.opposing_minutes == (5, 15, 30)


def test_extended_pyramid_can_add_on_15_and_30():
    t = datetime(2026, 9, 28, 12, tzinfo=timezone.utc)
    first = plan_macd_a_pyramid(state=PyramidState(), macd_a_direction="LONG", observed_direction="FLAT", crosses=(Cross(15,t,-1,1),), enabled_timeframes=(1,2,5,15,30))
    assert first.action == "OPEN" and first.amount == .02
    second = plan_macd_a_pyramid(state=first.state, macd_a_direction="LONG", observed_direction="LONG", crosses=(Cross(30,t,-1,1),), enabled_timeframes=(1,2,5,15,30))
    assert second.action == "ADD" and second.target_amount == .04


def test_legacy_and_extended_catalog_entries_are_distinct():
    assert strategy_spec_v2("macd-a-v1").label == "MACD-A"
    assert strategy_spec_v2("macd-a-pyr-v1").key == "macd-a-pyr-v1"
    assert strategy_spec_v2("macd-a-1-30-v1").label.startswith("MACD-A(1-30)")
    assert strategy_spec_v2("macd-a-pyr-1-30-v1").label.startswith("MACD-A-PYR(1-30)")
