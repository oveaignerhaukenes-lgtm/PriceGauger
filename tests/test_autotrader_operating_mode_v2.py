import pytest

from autotrader_operating_mode_v2 import (
    ACTION_ADD,
    ACTION_CLOSE,
    ACTION_FLIP,
    ACTION_HOLD,
    ACTION_OPEN,
    ACTION_REDUCE,
    autonomous_mode_v2,
    authorize_lifecycle_action_v2,
    guardian_mode_v2,
)


def test_autonomous_mode_allows_full_lifecycle_with_state_guards():
    mode = autonomous_mode_v2()

    assert authorize_lifecycle_action_v2(mode, requested_action=ACTION_OPEN, position_is_flat=True).allowed
    assert authorize_lifecycle_action_v2(mode, requested_action=ACTION_ADD, position_is_flat=False).allowed
    assert authorize_lifecycle_action_v2(mode, requested_action=ACTION_REDUCE, position_is_flat=False).allowed
    assert authorize_lifecycle_action_v2(mode, requested_action=ACTION_CLOSE, position_is_flat=False).allowed
    assert authorize_lifecycle_action_v2(
        mode,
        requested_action=ACTION_FLIP,
        position_is_flat=True,
    ).allowed


def test_guardian_can_hold_reduce_and_close_but_not_open_or_add():
    mode = guardian_mode_v2()

    assert authorize_lifecycle_action_v2(mode, requested_action=ACTION_HOLD, position_is_flat=False).allowed
    assert authorize_lifecycle_action_v2(mode, requested_action=ACTION_REDUCE, position_is_flat=False).allowed
    assert authorize_lifecycle_action_v2(mode, requested_action=ACTION_CLOSE, position_is_flat=False).allowed

    opened = authorize_lifecycle_action_v2(mode, requested_action=ACTION_OPEN, position_is_flat=True)
    added = authorize_lifecycle_action_v2(mode, requested_action=ACTION_ADD, position_is_flat=False)
    assert not opened.allowed
    assert "GUARDIAN_CANNOT_OPEN_INDEPENDENTLY" in opened.reasons
    assert not added.allowed
    assert "GUARDIAN_CANNOT_ADD_EXPOSURE" in added.reasons


def test_guardian_flip_is_fail_closed_by_default():
    decision = authorize_lifecycle_action_v2(
        guardian_mode_v2(),
        requested_action=ACTION_FLIP,
        position_is_flat=True,
        flip_origin_was_managed_position=True,
    )
    assert not decision.allowed
    assert decision.reasons == ("FLIP_NOT_ENABLED",)


def test_guardian_flip_requires_opt_in_confirmed_flat_and_managed_origin():
    mode = guardian_mode_v2(allow_flip=True)

    not_flat = authorize_lifecycle_action_v2(
        mode,
        requested_action=ACTION_FLIP,
        position_is_flat=False,
        flip_origin_was_managed_position=True,
    )
    wrong_origin = authorize_lifecycle_action_v2(
        mode,
        requested_action=ACTION_FLIP,
        position_is_flat=True,
        flip_origin_was_managed_position=False,
    )
    allowed = authorize_lifecycle_action_v2(
        mode,
        requested_action=ACTION_FLIP,
        position_is_flat=True,
        flip_origin_was_managed_position=True,
    )

    assert not not_flat.allowed
    assert "FLIP_REQUIRES_CONFIRMED_FLAT" in not_flat.reasons
    assert not wrong_origin.allowed
    assert "GUARDIAN_FLIP_REQUIRES_MANAGED_POSITION_ORIGIN" in wrong_origin.reasons
    assert allowed.allowed


def test_reduce_and_close_do_not_apply_entry_guards_but_require_position():
    mode = guardian_mode_v2()
    for action in (ACTION_REDUCE, ACTION_CLOSE):
        decision = authorize_lifecycle_action_v2(mode, requested_action=action, position_is_flat=True)
        assert not decision.allowed
        assert decision.reasons == (f"{action}_REQUIRES_EXISTING_POSITION",)


def test_unknown_mode_or_action_is_rejected():
    with pytest.raises(ValueError):
        guardian_mode_v2().__class__(mode="UNKNOWN")

    with pytest.raises(ValueError):
        authorize_lifecycle_action_v2(
            guardian_mode_v2(),
            requested_action="REVERSE_NOW",
            position_is_flat=False,
        )
