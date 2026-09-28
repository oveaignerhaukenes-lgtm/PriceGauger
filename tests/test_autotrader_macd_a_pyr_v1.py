from datetime import datetime, timezone, timedelta

import pytest

from autotrader_macd_a_pyr_v1 import Cross, PyramidState, plan_macd_a_pyramid


T = datetime(2026, 9, 28, 12, tzinfo=timezone.utc)


def cross(minutes, offset=0, direction="LONG"):
    return Cross(minutes, T + timedelta(minutes=offset), -1 if direction == "LONG" else 1, 1 if direction == "LONG" else -1)


def plan(state, direction="LONG", observed="FLAT", crosses=(), **kw):
    return plan_macd_a_pyramid(state=state, macd_a_direction=direction, observed_direction=observed, crosses=crosses, **kw)


def test_first_cross_opens_exact_002_and_duplicate_does_not_add():
    first = plan(PyramidState(), crosses=(cross(1),))
    assert (first.action, first.amount, first.target_amount) == ("OPEN", .02, .02)
    duplicate = plan(first.state, observed="LONG", crosses=(cross(1),))
    assert duplicate.action == "HOLD"


def test_subsequent_timeframe_adds_and_cap():
    state = plan(PyramidState(), crosses=(cross(1),)).state
    second = plan(state, observed="LONG", crosses=(cross(2),))
    assert (second.action, second.amount, second.target_amount) == ("ADD", .02, .04)
    capped = plan(second.state, observed="LONG", crosses=(cross(5),), max_amount=.04)
    assert capped.action == "HOLD"


def test_reversal_closes_then_requires_confirmed_flat():
    state = plan(PyramidState(), crosses=(cross(1),)).state
    closing = plan(state, direction="SHORT", observed="LONG", crosses=(cross(2, direction="SHORT"),))
    assert closing.action == "CLOSE"
    assert closing.state.pending_flat
    assert plan(closing.state, direction="SHORT", observed="LONG").action == "CLOSE"
    after = plan(closing.state, direction="SHORT", observed="FLAT")
    assert after.action == "HOLD"
    assert plan(after.state, direction="SHORT", crosses=(cross(2, 1, "SHORT"),)).action == "OPEN"


def test_opposite_cross_does_not_add_and_simultaneous_events_not_lost():
    first = plan(PyramidState(), crosses=(cross(1), cross(2), cross(5, direction="SHORT")))
    assert first.target_amount == .02
    second = plan(first.state, observed="LONG", crosses=(cross(1), cross(2)))
    assert second.action == "ADD"
    assert second.target_amount == .04


def test_external_flat_does_not_reopen_without_new_signal():
    state = plan(PyramidState(), crosses=(cross(1),)).state
    result = plan(state, crosses=(cross(1),))
    assert result.action == "HOLD"
    assert result.state.tranches == 0


@pytest.mark.parametrize("size,cap", [(-.02,.2),(.02,.01),(float("nan"),.2)])
def test_invalid_sizing_rejected(size,cap):
    with pytest.raises(ValueError):
        plan(PyramidState(), tranche_amount=size, max_amount=cap)


def test_catalog_registration_is_shadow_only():
    from autotrader_strategy_catalog_v2 import MACD_A_PYR_STRATEGY_V1, strategy_spec_v2
    assert MACD_A_PYR_STRATEGY_V1 == "macd-a-pyr-v1"
    assert "shadow" in strategy_spec_v2(MACD_A_PYR_STRATEGY_V1).label.lower()
