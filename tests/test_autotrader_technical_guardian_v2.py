from __future__ import annotations

import pytest

from autotrader_position_controller_v2 import ACTION_CLOSE, ACTION_HOLD, ACTION_REDUCE
from autotrader_technical_guardian_v2 import (
    TechnicalGuardianConfigV2,
    TechnicalGuardianObservationV2,
    evaluate_technical_guardian_v2,
)


def _obs(**overrides):
    values = {
        "position_direction": "LONG",
        "trend_state": "BEARISH",
        "momentum_state": "BEARISH",
        "structure_state": "LH_LL",
        "technical_score": -0.60,
        "confidence": 0.80,
        "opposing_cycles": 2,
    }
    values.update(overrides)
    return TechnicalGuardianObservationV2(**values)


def test_long_position_closes_after_persistent_strong_bearish_regime() -> None:
    decision = evaluate_technical_guardian_v2(_obs())
    assert decision.action == ACTION_CLOSE
    assert decision.flip_candidate is False  # -0.60 is close-quality, not flip threshold.
    assert decision.flip_direction is None
    assert decision.risk_reducing is True


def test_long_position_marks_short_flip_candidate_only_after_stronger_persistent_regime() -> None:
    decision = evaluate_technical_guardian_v2(
        _obs(technical_score=-0.72, opposing_cycles=2)
    )
    assert decision.action == ACTION_CLOSE
    assert decision.flip_candidate is True
    assert decision.flip_direction == "SHORT"
    assert any("confirmed FLAT" in item for item in decision.rationale)


def test_short_policy_is_exact_mirror_of_long_policy() -> None:
    decision = evaluate_technical_guardian_v2(
        _obs(
            position_direction="SHORT",
            trend_state="BULLISH",
            momentum_state="BULLISH",
            structure_state="HH_HL",
            technical_score=0.72,
        )
    )
    assert decision.action == ACTION_CLOSE
    assert decision.flip_candidate is True
    assert decision.flip_direction == "LONG"


def test_first_non_extreme_opposing_cycle_reduces_instead_of_closing() -> None:
    decision = evaluate_technical_guardian_v2(_obs(opposing_cycles=1))
    assert decision.action == ACTION_REDUCE
    assert decision.flip_candidate is False
    assert "OPEN" not in {decision.action}


def test_extreme_full_agreement_can_close_in_one_cycle_but_cannot_flip_yet() -> None:
    decision = evaluate_technical_guardian_v2(
        _obs(technical_score=-0.82, confidence=0.90, opposing_cycles=1)
    )
    assert decision.action == ACTION_CLOSE
    assert decision.flip_candidate is False
    assert decision.flip_direction is None


def test_mixed_weak_deterioration_holds() -> None:
    decision = evaluate_technical_guardian_v2(
        _obs(
            trend_state="BEARISH",
            momentum_state="NEUTRAL",
            structure_state="MIXED",
            technical_score=-0.12,
            confidence=0.90,
            opposing_cycles=4,
        )
    )
    assert decision.action == ACTION_HOLD
    assert decision.flip_candidate is False


def test_two_opposing_signals_with_material_score_reduce() -> None:
    decision = evaluate_technical_guardian_v2(
        _obs(
            trend_state="BEARISH",
            momentum_state="NEUTRAL",
            structure_state="MIXED",
            technical_score=-0.30,
            confidence=0.60,
            opposing_cycles=1,
        )
    )
    assert decision.action == ACTION_REDUCE
    assert decision.opposing_votes == 2


def test_low_confidence_blocks_normal_close() -> None:
    decision = evaluate_technical_guardian_v2(_obs(confidence=0.40, opposing_cycles=5))
    assert decision.action == ACTION_REDUCE
    assert decision.flip_candidate is False


def test_policy_never_returns_open_or_add() -> None:
    scenarios = (
        _obs(),
        _obs(opposing_cycles=1),
        _obs(
            trend_state="BULLISH",
            momentum_state="BULLISH",
            structure_state="HH_HL",
            technical_score=0.50,
        ),
    )
    for observation in scenarios:
        assert evaluate_technical_guardian_v2(observation).action in {
            ACTION_HOLD,
            ACTION_REDUCE,
            ACTION_CLOSE,
        }


def test_observation_requires_existing_direction_and_bounded_values() -> None:
    with pytest.raises(ValueError):
        _obs(position_direction="FLAT")
    with pytest.raises(ValueError):
        _obs(technical_score=-1.1)
    with pytest.raises(ValueError):
        _obs(confidence=1.1)
    with pytest.raises(ValueError):
        _obs(opposing_cycles=0)


def test_config_preserves_reduce_close_flip_ordering() -> None:
    with pytest.raises(ValueError):
        TechnicalGuardianConfigV2(reduce_score_threshold=0.6, close_score_threshold=0.5)
    with pytest.raises(ValueError):
        TechnicalGuardianConfigV2(close_score_threshold=0.7, flip_score_threshold=0.6)
    with pytest.raises(ValueError):
        TechnicalGuardianConfigV2(
            minimum_opposing_cycles_for_close=3,
            minimum_opposing_cycles_for_flip=2,
        )
