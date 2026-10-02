from autotrader_v2_armed_state_v1 import (
    STATE_ARMED,
    STATE_BLOCKED,
    STATE_LIVE,
    STATE_OFF,
    cockpit_state_v1,
    minimum_capital_for_notional_v1,
)


def _state(**overrides):
    values = dict(
        live_requested=False,
        guard_blocked=False,
        guard_reason=None,
        preflight_ready=False,
        observed_direction="FLAT",
        desired_direction=None,
    )
    values.update(overrides)
    return cockpit_state_v1(**values)


def test_preflight_ready_without_authority_is_armed():
    state = _state(preflight_ready=True)
    assert state.state == STATE_ARMED
    assert state.indicator == "ARMED"
    assert not state.live_requested


def test_go_live_is_the_only_transition_that_yields_live():
    state = _state(preflight_ready=True, live_requested=True, desired_direction="long")
    assert state.state == STATE_LIVE
    assert state.indicator == "RECORD"
    assert state.desired_direction == "LONG"


def test_guard_preserves_live_intent_but_surfaces_blocked():
    state = _state(
        preflight_ready=True,
        live_requested=True,
        guard_blocked=True,
        guard_reason="FREE_CAPITAL_BUFFER",
    )
    assert state.state == STATE_BLOCKED
    assert state.indicator == "ALERT"
    assert state.live_requested
    assert state.guard_reason == "FREE_CAPITAL_BUFFER"


def test_unconfigured_is_off():
    assert _state().state == STATE_OFF


def test_minimum_capital_is_visible_from_minimum_notional_and_leverage():
    assert minimum_capital_for_notional_v1(3140.0, 5.0) == 628.0
    assert minimum_capital_for_notional_v1(None, 5.0) is None
    assert minimum_capital_for_notional_v1(3140.0, 0.0) is None
