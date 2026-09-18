from pathlib import Path

import pandas as pd

from autotrader_macd_supervisor_normalized_replay_v1 import (
    NormalizedMacdTimeframeStateV1,
    _normalize_spread_history,
    evaluate_normalized_macd_supervisor_v1,
)


def _state(minutes: int, strength: float, previous: float) -> NormalizedMacdTimeframeStateV1:
    return NormalizedMacdTimeframeStateV1(
        minutes=minutes,
        strength=strength,
        previous_strength=previous,
    )


def test_per_timeframe_normalization_is_scale_invariant() -> None:
    base = pd.Series([0.03 + (index * 0.007) for index in range(80)], dtype="float64")
    normal = _normalize_spread_history(base)
    scaled = _normalize_spread_history(base * 137.0)
    pd.testing.assert_series_equal(normal, scaled, check_exact=False, rtol=1e-12, atol=1e-12)


def test_flat_history_keeps_numeric_dtype_when_scale_is_zero() -> None:
    spread = pd.Series(([0.0] * 12) + [0.05, 0.10, 0.15, 0.20], dtype="float64")
    normalized = _normalize_spread_history(spread)
    assert str(normalized.dtype) == "float64"
    assert normalized.iloc[:12].isna().all()


def test_fast_cascade_can_override_stale_slow_context_when_propagation_is_strong() -> None:
    states = {
        1: _state(1, 0.75, 0.20),
        2: _state(2, 0.70, 0.10),
        5: _state(5, 0.65, 0.00),
        10: _state(10, 0.50, -0.10),
        15: _state(15, -0.25, -0.30),
        30: _state(30, -0.40, -0.45),
    }
    decision = evaluate_normalized_macd_supervisor_v1(states, current_target=-1)
    assert decision.context_score < 0.0
    assert decision.change_score > 0.45
    assert decision.target == 1


def test_isolated_micro_false_start_does_not_reverse_slow_bearish_regime() -> None:
    states = {
        1: _state(1, 0.80, 0.10),
        2: _state(2, -0.20, -0.25),
        5: _state(5, -0.40, -0.45),
        10: _state(10, -0.50, -0.48),
        15: _state(15, -0.60, -0.58),
        30: _state(30, -0.60, -0.59),
    }
    decision = evaluate_normalized_macd_supervisor_v1(states, current_target=-1)
    assert decision.target == -1
    assert decision.score < 0.0



def test_normalized_closed_5m_cross_up_is_authoritative_over_bearish_score() -> None:
    states = {
        1: _state(1, -0.20, -0.25),
        2: _state(2, -0.30, -0.35),
        5: _state(5, 0.02, -0.03),
        10: _state(10, -0.70, -0.68),
        15: _state(15, -0.90, -0.88),
        30: _state(30, -1.00, -0.98),
    }
    decision = evaluate_normalized_macd_supervisor_v1(states, current_target=-1)
    assert decision.context_score < 0.0
    assert decision.score < 0.0
    assert decision.target == 1
    assert "authoritative 5m CROSS_UP" in decision.explanation


def test_normalized_closed_5m_cross_down_is_authoritative_over_bullish_score() -> None:
    states = {
        1: _state(1, 0.20, 0.25),
        2: _state(2, 0.30, 0.35),
        5: _state(5, -0.02, 0.03),
        10: _state(10, 0.70, 0.68),
        15: _state(15, 0.90, 0.88),
        30: _state(30, 1.00, 0.98),
    }
    decision = evaluate_normalized_macd_supervisor_v1(states, current_target=1)
    assert decision.context_score > 0.0
    assert decision.score > 0.0
    assert decision.target == -1
    assert "authoritative 5m CROSS_DOWN" in decision.explanation

def test_normalized_supervisor_has_no_execution_authority() -> None:
    source = (
        Path(__file__).resolve().parents[1] / "autotrader_macd_supervisor_normalized_replay_v1.py"
    ).read_text(encoding="utf-8").lower()
    for token in ("saxo", "order_request", "request_manual_target", "persist_intent"):
        assert token not in source
