import pytest

from forecast_path import (
    ForecastPathEvidence,
    analysis_path_move,
    technical_direction_from_regime,
    transient_path_uncertainty_pct,
)


def test_technical_direction_is_recovered_from_runtime_regime_label():
    assert technical_direction_from_regime("BULLISH · HIGH · TREND") == 1.0
    assert technical_direction_from_regime("SLIGHTLY BULLISH · MEDIUM · RANGE") == 0.45
    assert technical_direction_from_regime("SLIGHTLY BEARISH · MEDIUM · RANGE") == -0.45
    assert technical_direction_from_regime("BEARISH · HIGH · TREND") == -1.0
    assert technical_direction_from_regime("NEUTRAL · LOW · RANGE") == 0.0


def test_aligned_technical_state_frontloads_bullish_thesis_without_changing_endpoint():
    evidence = ForecastPathEvidence("BULLISH · HIGH · TREND", 0.3)
    midpoint = analysis_path_move(
        0.5,
        1.0,
        decision_score=0.7,
        confidence=0.8,
        evidence=evidence,
    )
    assert midpoint > 0.5
    assert analysis_path_move(1.0, 1.0, decision_score=0.7, confidence=0.8, evidence=evidence) == 1.0


def test_opposing_technical_state_can_show_initial_countermove_before_bullish_endpoint():
    evidence = ForecastPathEvidence("BEARISH · HIGH · TREND", 0.9)
    early = analysis_path_move(
        0.1,
        1.0,
        decision_score=0.7,
        confidence=0.8,
        evidence=evidence,
    )
    later = analysis_path_move(
        0.75,
        1.0,
        decision_score=0.7,
        confidence=0.8,
        evidence=evidence,
    )
    assert early < 0.0
    assert later > 0.0
    assert analysis_path_move(1.0, 1.0, decision_score=0.7, confidence=0.8, evidence=evidence) == 1.0


def test_path_model_is_directionally_symmetric():
    evidence = ForecastPathEvidence("BULLISH · HIGH · TREND", 0.9)
    early_short = analysis_path_move(
        0.1,
        -1.0,
        decision_score=-0.7,
        confidence=0.8,
        evidence=evidence,
    )
    assert early_short > 0.0
    assert analysis_path_move(1.0, -1.0, decision_score=-0.7, confidence=0.8, evidence=evidence) == -1.0


def test_transient_uncertainty_is_intrahorizon_only_and_grows_with_volatility():
    calm = ForecastPathEvidence("BULLISH · HIGH · TREND", 0.1)
    volatile = ForecastPathEvidence("BULLISH · HIGH · TREND", 0.9)
    calm_mid = transient_path_uncertainty_pct(0.5, 1.0, confidence=0.7, evidence=calm)
    volatile_mid = transient_path_uncertainty_pct(0.5, 1.0, confidence=0.7, evidence=volatile)
    assert volatile_mid > calm_mid > 0.0
    assert transient_path_uncertainty_pct(0.0, 1.0, confidence=0.7, evidence=volatile) == 0.0
    assert transient_path_uncertainty_pct(1.0, 1.0, confidence=0.7, evidence=volatile) == 0.0


def test_neutral_technical_evidence_does_not_invent_non_linear_shape():
    evidence = ForecastPathEvidence("NEUTRAL · LOW · RANGE", 0.8)
    assert analysis_path_move(0.25, 0.8, decision_score=0.5, confidence=0.5, evidence=evidence) == pytest.approx(0.2)
    assert analysis_path_move(0.5, 0.8, decision_score=0.5, confidence=0.5, evidence=evidence) == pytest.approx(0.4)
