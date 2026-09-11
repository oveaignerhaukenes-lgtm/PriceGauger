from autotrader_macd_supervisor_v1 import MacdTimeframeStateV1, evaluate_macd_supervisor_v1


def _states(values, previous=None):
    previous = previous or values
    return {
        minutes: MacdTimeframeStateV1(minutes, float(values[minutes]), float(previous[minutes]))
        for minutes in (1, 2, 5, 10, 15, 30)
    }


def test_strong_slow_uptrend_ignores_small_micro_pullback():
    values = {1: -0.05, 2: -0.03, 5: 0.20, 10: 0.45, 15: 0.80, 30: 1.00}
    previous = {1: 0.02, 2: 0.01, 5: 0.18, 10: 0.40, 15: 0.75, 30: 0.95}
    decision = evaluate_macd_supervisor_v1(_states(values, previous), current_target=1)
    assert decision.target == 1
    assert decision.context_score > 0.0
    assert "LONG" in decision.explanation


def test_propagating_fast_reversal_can_anticipate_slow_cross():
    values = {1: -0.80, 2: -0.75, 5: -0.65, 10: -0.45, 15: -0.10, 30: 0.20}
    previous = {1: -0.40, 2: -0.30, 5: -0.20, 10: 0.05, 15: 0.10, 30: 0.30}
    decision = evaluate_macd_supervisor_v1(_states(values, previous), current_target=1)
    assert decision.target == -1
    assert decision.change_score < 0.0
    assert "SHORT" in decision.explanation


def test_isolated_one_minute_cross_does_not_reverse_strong_context():
    values = {1: -0.40, 2: 0.20, 5: 0.45, 10: 0.60, 15: 0.80, 30: 1.00}
    previous = {1: 0.10, 2: 0.18, 5: 0.40, 10: 0.55, 15: 0.75, 30: 0.95}
    decision = evaluate_macd_supervisor_v1(_states(values, previous), current_target=1)
    assert decision.target == 1


def test_ambiguous_score_holds_existing_position_instead_of_churning():
    values = {1: -0.02, 2: 0.01, 5: -0.01, 10: 0.01, 15: -0.01, 30: 0.01}
    decision = evaluate_macd_supervisor_v1(_states(values), current_target=-1)
    assert decision.target == -1
    assert "SHORT" in decision.explanation


def test_requires_all_timeframes():
    states = _states({1: 1, 2: 1, 5: 1, 10: 1, 15: 1, 30: 1})
    states.pop(10)
    try:
        evaluate_macd_supervisor_v1(states)
    except ValueError as exc:
        assert "10" in str(exc)
    else:
        raise AssertionError("missing timeframe must fail closed")
