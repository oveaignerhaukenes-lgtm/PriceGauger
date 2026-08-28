from __future__ import annotations

from dataclasses import dataclass


MODE_AUTONOMOUS = "AUTONOMOUS"
MODE_GUARDIAN = "GUARDIAN"
VALID_MODES = {MODE_AUTONOMOUS, MODE_GUARDIAN}

ACTION_HOLD = "HOLD"
ACTION_OPEN = "OPEN"
ACTION_ADD = "ADD"
ACTION_REDUCE = "REDUCE"
ACTION_CLOSE = "CLOSE"
ACTION_FLIP = "FLIP"
VALID_ACTIONS = {
    ACTION_HOLD,
    ACTION_OPEN,
    ACTION_ADD,
    ACTION_REDUCE,
    ACTION_CLOSE,
    ACTION_FLIP,
}


@dataclass(frozen=True, slots=True)
class AutoTraderOperatingModeV2:
    """Authority contract above strategy and below product/risk controls.

    The mode never changes product eligibility, margin limits, Saxo precheck or the
    close-flat-open reversal invariant. It only defines which lifecycle requests a
    strategy is allowed to make.
    """

    mode: str
    allow_flip: bool = False

    def __post_init__(self) -> None:
        normalized = str(self.mode).upper()
        if normalized not in VALID_MODES:
            raise ValueError(f"unsupported AutoTrader operating mode: {self.mode}")
        if normalized == MODE_GUARDIAN and self.allow_flip not in {True, False}:
            raise ValueError("allow_flip must be boolean")

    @property
    def normalized_mode(self) -> str:
        return str(self.mode).upper()

    @property
    def may_open_independently(self) -> bool:
        return self.normalized_mode == MODE_AUTONOMOUS

    @property
    def may_add(self) -> bool:
        return self.normalized_mode == MODE_AUTONOMOUS

    @property
    def may_reduce(self) -> bool:
        return True

    @property
    def may_close(self) -> bool:
        return True

    @property
    def may_flip_after_confirmed_flat(self) -> bool:
        return self.normalized_mode == MODE_AUTONOMOUS or bool(self.allow_flip)


@dataclass(frozen=True, slots=True)
class OperatingModeDecisionV2:
    allowed: bool
    requested_action: str
    reasons: tuple[str, ...]


def authorize_lifecycle_action_v2(
    operating_mode: AutoTraderOperatingModeV2,
    *,
    requested_action: str,
    position_is_flat: bool,
    flip_origin_was_managed_position: bool = False,
) -> OperatingModeDecisionV2:
    """Authorize one requested lifecycle action before execution planning.

    Guardian is deliberately asymmetric: it can always reduce/close an enrolled
    position, but it cannot create or add exposure. Optional flip authority is only
    meaningful after the original managed position has been closed and the observed
    account state is confirmed flat. The actual opposite OPEN remains a later cycle.
    """

    action = str(requested_action).upper()
    if action not in VALID_ACTIONS:
        raise ValueError(f"unsupported lifecycle action: {requested_action}")

    reasons: list[str] = []
    mode = operating_mode.normalized_mode

    if action == ACTION_HOLD:
        return OperatingModeDecisionV2(True, action, ())

    if action == ACTION_OPEN:
        if not position_is_flat:
            reasons.append("OPEN_REQUIRES_CONFIRMED_FLAT")
        if mode == MODE_GUARDIAN:
            reasons.append("GUARDIAN_CANNOT_OPEN_INDEPENDENTLY")

    elif action == ACTION_ADD:
        if mode == MODE_GUARDIAN:
            reasons.append("GUARDIAN_CANNOT_ADD_EXPOSURE")
        if position_is_flat:
            reasons.append("ADD_REQUIRES_EXISTING_POSITION")

    elif action in {ACTION_REDUCE, ACTION_CLOSE}:
        if position_is_flat:
            reasons.append(f"{action}_REQUIRES_EXISTING_POSITION")

    elif action == ACTION_FLIP:
        if not operating_mode.may_flip_after_confirmed_flat:
            reasons.append("FLIP_NOT_ENABLED")
        if not position_is_flat:
            reasons.append("FLIP_REQUIRES_CONFIRMED_FLAT")
        if mode == MODE_GUARDIAN and not flip_origin_was_managed_position:
            reasons.append("GUARDIAN_FLIP_REQUIRES_MANAGED_POSITION_ORIGIN")

    return OperatingModeDecisionV2(not reasons, action, tuple(reasons))


def autonomous_mode_v2() -> AutoTraderOperatingModeV2:
    return AutoTraderOperatingModeV2(mode=MODE_AUTONOMOUS, allow_flip=True)


def guardian_mode_v2(*, allow_flip: bool = False) -> AutoTraderOperatingModeV2:
    return AutoTraderOperatingModeV2(mode=MODE_GUARDIAN, allow_flip=allow_flip)
