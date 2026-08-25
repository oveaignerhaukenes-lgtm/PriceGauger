from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


DIRECTION_FLAT = "FLAT"
DIRECTION_LONG = "LONG"
DIRECTION_SHORT = "SHORT"
VALID_DIRECTIONS = {DIRECTION_FLAT, DIRECTION_LONG, DIRECTION_SHORT}

ACTION_HOLD = "HOLD"
ACTION_OPEN = "OPEN"
ACTION_ADD = "ADD"
ACTION_REDUCE = "REDUCE"
ACTION_CLOSE = "CLOSE"
VALID_ACTIONS = {ACTION_HOLD, ACTION_OPEN, ACTION_ADD, ACTION_REDUCE, ACTION_CLOSE}


@dataclass(frozen=True, slots=True)
class PositionTargetV2:
    """Strategy output expressed as desired exposure, independent of execution.

    `target_fraction` is the fraction of the strategy budget that should be deployed
    in `direction`. A FLAT target must always be zero. The target is intentionally
    product-agnostic: product discovery/sizing happens downstream.
    """

    market_id: int
    market_name: str
    direction: str
    target_fraction: float
    budget_amount: float
    budget_currency: str
    strategy_key: str
    signal_at: datetime
    rationale: str
    source_fingerprint: str = ""

    def __post_init__(self) -> None:
        direction = str(self.direction).upper()
        if direction not in VALID_DIRECTIONS:
            raise ValueError(f"unsupported target direction: {self.direction}")
        if not 0.0 <= float(self.target_fraction) <= 1.0:
            raise ValueError("target_fraction must be between 0 and 1")
        if direction == DIRECTION_FLAT and abs(float(self.target_fraction)) > 1e-12:
            raise ValueError("FLAT target must have target_fraction=0")
        if float(self.budget_amount) <= 0:
            raise ValueError("budget_amount must be positive")
        if not str(self.budget_currency).strip():
            raise ValueError("budget_currency is required")
        if not str(self.strategy_key).strip():
            raise ValueError("strategy_key is required")
        if self.signal_at.tzinfo is None:
            raise ValueError("signal_at must be timezone-aware")

    @property
    def target_budget_amount(self) -> float:
        return float(self.budget_amount) * float(self.target_fraction)


@dataclass(frozen=True, slots=True)
class PositionStateV2:
    """Observed strategy exposure before execution planning.

    `deployed_fraction` is measured against the same strategy budget as the target.
    Execution adapters are responsible for deriving it from the actual Saxo product
    position/value; the controller never infers position state from analysis output.
    """

    direction: str = DIRECTION_FLAT
    deployed_fraction: float = 0.0

    def __post_init__(self) -> None:
        direction = str(self.direction).upper()
        if direction not in VALID_DIRECTIONS:
            raise ValueError(f"unsupported current direction: {self.direction}")
        if not 0.0 <= float(self.deployed_fraction) <= 1.0:
            raise ValueError("deployed_fraction must be between 0 and 1")
        if direction == DIRECTION_FLAT and abs(float(self.deployed_fraction)) > 1e-12:
            raise ValueError("FLAT position must have deployed_fraction=0")


@dataclass(frozen=True, slots=True)
class PositionDecisionV2:
    action: str
    prior_direction: str
    desired_direction: str
    prior_fraction: float
    target_fraction: float
    delta_fraction: float
    rationale: str

    def __post_init__(self) -> None:
        if self.action not in VALID_ACTIONS:
            raise ValueError(f"unsupported position action: {self.action}")
        if self.prior_direction not in VALID_DIRECTIONS:
            raise ValueError("invalid prior_direction")
        if self.desired_direction not in VALID_DIRECTIONS:
            raise ValueError("invalid desired_direction")



def _normalized_direction(value: str) -> str:
    direction = str(value).upper()
    if direction not in VALID_DIRECTIONS:
        raise ValueError(f"unsupported direction: {value}")
    return direction


def decide_position_action_v2(
    current: PositionStateV2,
    target: PositionTargetV2,
    *,
    rebalance_threshold: float = 0.05,
) -> PositionDecisionV2:
    """Translate desired exposure into one bounded lifecycle action.

    Safety invariant: a direction reversal is always sequenced as CLOSE first.
    The controller never returns a combined reverse order. A later cycle may OPEN
    the opposite direction only after the observed position is confirmed FLAT.
    """

    threshold = float(rebalance_threshold)
    if threshold < 0 or threshold > 1:
        raise ValueError("rebalance_threshold must be between 0 and 1")

    prior_direction = _normalized_direction(current.direction)
    desired_direction = _normalized_direction(target.direction)
    prior_fraction = float(current.deployed_fraction)
    target_fraction = float(target.target_fraction)

    if desired_direction == DIRECTION_FLAT or target_fraction <= 1e-12:
        if prior_direction == DIRECTION_FLAT or prior_fraction <= 1e-12:
            return PositionDecisionV2(
                action=ACTION_HOLD,
                prior_direction=prior_direction,
                desired_direction=DIRECTION_FLAT,
                prior_fraction=prior_fraction,
                target_fraction=0.0,
                delta_fraction=0.0,
                rationale="already flat",
            )
        return PositionDecisionV2(
            action=ACTION_CLOSE,
            prior_direction=prior_direction,
            desired_direction=DIRECTION_FLAT,
            prior_fraction=prior_fraction,
            target_fraction=0.0,
            delta_fraction=-prior_fraction,
            rationale="target is flat",
        )

    if prior_direction == DIRECTION_FLAT or prior_fraction <= 1e-12:
        return PositionDecisionV2(
            action=ACTION_OPEN,
            prior_direction=DIRECTION_FLAT,
            desired_direction=desired_direction,
            prior_fraction=0.0,
            target_fraction=target_fraction,
            delta_fraction=target_fraction,
            rationale=target.rationale or "open toward target exposure",
        )

    if prior_direction != desired_direction:
        return PositionDecisionV2(
            action=ACTION_CLOSE,
            prior_direction=prior_direction,
            desired_direction=desired_direction,
            prior_fraction=prior_fraction,
            target_fraction=target_fraction,
            delta_fraction=-prior_fraction,
            rationale="direction change requires confirmed flat state before reopening",
        )

    difference = target_fraction - prior_fraction
    if abs(difference) < threshold:
        return PositionDecisionV2(
            action=ACTION_HOLD,
            prior_direction=prior_direction,
            desired_direction=desired_direction,
            prior_fraction=prior_fraction,
            target_fraction=target_fraction,
            delta_fraction=0.0,
            rationale="within rebalance threshold",
        )

    if difference > 0:
        return PositionDecisionV2(
            action=ACTION_ADD,
            prior_direction=prior_direction,
            desired_direction=desired_direction,
            prior_fraction=prior_fraction,
            target_fraction=target_fraction,
            delta_fraction=difference,
            rationale=target.rationale or "increase toward target exposure",
        )

    return PositionDecisionV2(
        action=ACTION_REDUCE,
        prior_direction=prior_direction,
        desired_direction=desired_direction,
        prior_fraction=prior_fraction,
        target_fraction=target_fraction,
        delta_fraction=difference,
        rationale=target.rationale or "reduce toward target exposure",
    )


def utc_now_v2() -> datetime:
    return datetime.now(timezone.utc)
