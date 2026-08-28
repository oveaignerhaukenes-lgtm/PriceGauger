from __future__ import annotations

from dataclasses import dataclass

from autotrader_position_controller_v2 import (
    ACTION_CLOSE,
    ACTION_HOLD,
    ACTION_REDUCE,
    DIRECTION_LONG,
    DIRECTION_SHORT,
)


TECHNICAL_GUARDIAN_RECIPE_V1 = "technical-guardian-v1.0"


@dataclass(frozen=True, slots=True)
class TechnicalGuardianConfigV2:
    """Deterministic TA-only thresholds for protecting an existing position.

    The policy has no execution authority. It may recommend HOLD, REDUCE or CLOSE.
    A flip is represented only as a candidate after a CLOSE-quality opposing regime;
    the operating-mode/execution layers still require confirmed FLAT state before a
    later opposite OPEN can even be considered.
    """

    reduce_score_threshold: float = 0.20
    close_score_threshold: float = 0.50
    flip_score_threshold: float = 0.65
    minimum_confidence_for_close: float = 0.55
    minimum_opposing_cycles_for_close: int = 2
    minimum_opposing_cycles_for_flip: int = 2

    def __post_init__(self) -> None:
        for name in ("reduce_score_threshold", "close_score_threshold", "flip_score_threshold"):
            value = float(getattr(self, name))
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")
        if not 0.0 <= float(self.minimum_confidence_for_close) <= 1.0:
            raise ValueError("minimum_confidence_for_close must be between 0 and 1")
        if int(self.minimum_opposing_cycles_for_close) < 1:
            raise ValueError("minimum_opposing_cycles_for_close must be >= 1")
        if int(self.minimum_opposing_cycles_for_flip) < int(self.minimum_opposing_cycles_for_close):
            raise ValueError("minimum_opposing_cycles_for_flip cannot be below close persistence")
        if float(self.close_score_threshold) < float(self.reduce_score_threshold):
            raise ValueError("close_score_threshold cannot be below reduce_score_threshold")
        if float(self.flip_score_threshold) < float(self.close_score_threshold):
            raise ValueError("flip_score_threshold cannot be below close_score_threshold")


@dataclass(frozen=True, slots=True)
class TechnicalGuardianObservationV2:
    position_direction: str
    trend_state: str
    momentum_state: str
    structure_state: str
    technical_score: float
    confidence: float
    opposing_cycles: int = 1

    def __post_init__(self) -> None:
        direction = str(self.position_direction).upper()
        if direction not in {DIRECTION_LONG, DIRECTION_SHORT}:
            raise ValueError("Technical Guardian requires an existing LONG or SHORT position")
        if not -1.0 <= float(self.technical_score) <= 1.0:
            raise ValueError("technical_score must be between -1 and 1")
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        if int(self.opposing_cycles) < 1:
            raise ValueError("opposing_cycles must be >= 1")


@dataclass(frozen=True, slots=True)
class TechnicalGuardianDecisionV2:
    action: str
    opposition_score: float
    opposing_votes: int
    opposing_cycles: int
    flip_candidate: bool
    flip_direction: str | None
    rationale: tuple[str, ...]
    recipe_version: str = TECHNICAL_GUARDIAN_RECIPE_V1

    @property
    def risk_reducing(self) -> bool:
        return self.action in {ACTION_HOLD, ACTION_REDUCE, ACTION_CLOSE}


def _normalized_state(value: str) -> str:
    return str(value or "").strip().upper()


def _opposite_direction(direction: str) -> str:
    return DIRECTION_SHORT if direction == DIRECTION_LONG else DIRECTION_LONG


def _opposing_sign(direction: str) -> float:
    # A negative technical score opposes LONG; a positive score opposes SHORT.
    return -1.0 if direction == DIRECTION_LONG else 1.0


def evaluate_technical_guardian_v2(
    observation: TechnicalGuardianObservationV2,
    *,
    config: TechnicalGuardianConfigV2 | None = None,
) -> TechnicalGuardianDecisionV2:
    """Convert canonical Technical Core state into a bounded Guardian recommendation.

    This deliberately reasons only about whether an *existing* position is still
    supported by technicals. It never returns OPEN or ADD and never sends orders.

    Two safeguards reduce flip-flopping:
    1. CLOSE normally requires the opposing regime to persist across multiple cycles.
    2. A one-cycle emergency CLOSE is possible only when score, votes and confidence
       are all unusually strong; even then the opposite side is not opened here.
    """

    config = config or TechnicalGuardianConfigV2()
    direction = str(observation.position_direction).upper()
    opposite = _opposite_direction(direction)
    expected_opposing_state = "BEARISH" if direction == DIRECTION_LONG else "BULLISH"
    expected_opposing_structure = "LH_LL" if direction == DIRECTION_LONG else "HH_HL"

    trend = _normalized_state(observation.trend_state)
    momentum = _normalized_state(observation.momentum_state)
    structure = _normalized_state(observation.structure_state)
    score = float(observation.technical_score)
    confidence = float(observation.confidence)
    cycles = int(observation.opposing_cycles)

    signed_opposition = max(0.0, score * _opposing_sign(direction))
    rationale: list[str] = []
    votes = 0

    if trend == expected_opposing_state:
        votes += 1
        rationale.append(f"trend {trend} opposes {direction}")
    if momentum == expected_opposing_state:
        votes += 1
        rationale.append(f"momentum {momentum} opposes {direction}")
    if structure == expected_opposing_structure:
        votes += 1
        rationale.append(f"structure {structure} opposes {direction}")
    if signed_opposition >= float(config.reduce_score_threshold):
        votes += 1
        rationale.append(f"technical score {score:+.3f} opposes {direction}")

    persistent_close = (
        votes >= 3
        and signed_opposition >= float(config.close_score_threshold)
        and confidence >= float(config.minimum_confidence_for_close)
        and cycles >= int(config.minimum_opposing_cycles_for_close)
    )
    emergency_close = (
        votes >= 4
        and signed_opposition >= max(0.75, float(config.flip_score_threshold))
        and confidence >= max(0.70, float(config.minimum_confidence_for_close))
    )

    if persistent_close or emergency_close:
        if persistent_close:
            rationale.append(f"opposing regime persisted for {cycles} cycles")
        else:
            rationale.append("extreme one-cycle opposition qualifies for protective CLOSE")
        flip_candidate = (
            votes >= 3
            and signed_opposition >= float(config.flip_score_threshold)
            and confidence >= float(config.minimum_confidence_for_close)
            and cycles >= int(config.minimum_opposing_cycles_for_flip)
        )
        if flip_candidate:
            rationale.append(f"opposite {opposite} may be reconsidered only after confirmed FLAT")
        return TechnicalGuardianDecisionV2(
            action=ACTION_CLOSE,
            opposition_score=round(signed_opposition, 6),
            opposing_votes=votes,
            opposing_cycles=cycles,
            flip_candidate=flip_candidate,
            flip_direction=opposite if flip_candidate else None,
            rationale=tuple(rationale),
        )

    reduce = votes >= 2 and signed_opposition >= float(config.reduce_score_threshold)
    if reduce:
        if cycles < int(config.minimum_opposing_cycles_for_close):
            rationale.append("opposition not yet persistent enough for normal CLOSE")
        return TechnicalGuardianDecisionV2(
            action=ACTION_REDUCE,
            opposition_score=round(signed_opposition, 6),
            opposing_votes=votes,
            opposing_cycles=cycles,
            flip_candidate=False,
            flip_direction=None,
            rationale=tuple(rationale),
        )

    if not rationale:
        rationale.append("no material opposing technical regime")
    return TechnicalGuardianDecisionV2(
        action=ACTION_HOLD,
        opposition_score=round(signed_opposition, 6),
        opposing_votes=votes,
        opposing_cycles=cycles,
        flip_candidate=False,
        flip_direction=None,
        rationale=tuple(rationale),
    )
