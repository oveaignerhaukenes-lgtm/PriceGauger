from __future__ import annotations

import pandas as pd

from autotrader_market_state_overseer_v1 import (
    FLAT_MODEL_V1,
    MarketStateV1,
    choose_model_v1,
    market_state_v1,
)


def _states(rows: int = 40) -> pd.DataFrame:
    idx = pd.date_range("2026-09-01", periods=rows, freq="5min", tz="UTC")
    return pd.DataFrame(
        {
            "efficiency": [0.78] * rows,
            "persistence": [0.82] * rows,
            "noise": [0.16] * rows,
            "volatility": [0.55] * rows,
            "volatility_acceleration": [0.62] * rows,
            "impulse": [0.66] * rows,
            "reversal_rate": [0.18] * rows,
        },
        index=idx,
    )


def test_market_state_detects_directional_move_as_lower_noise():
    trend = pd.Series([100 + i * 1.2 for i in range(60)])
    chop = pd.Series([100 + (1 if i % 2 else -1) for i in range(60)])
    trend_state = market_state_v1(trend)
    chop_state = market_state_v1(chop)
    assert trend_state.efficiency > chop_state.efficiency
    assert trend_state.noise < chop_state.noise


def test_overseer_selects_model_that_wins_in_similar_states():
    states = _states()
    returns = pd.DataFrame(
        {"MACD-A": [0.20] * len(states), "SFL-2m": [-0.03] * len(states)},
        index=states.index,
    )
    current = MarketStateV1(0.78, 0.82, 0.16, 0.55, 0.62, 0.66, 0.18)
    decision = choose_model_v1(current, states, returns, risk=0.8)
    assert decision.model == "MACD-A"
    assert decision.confidence > 0.5


def test_flat_is_selected_when_no_model_has_positive_edge():
    states = _states()
    returns = pd.DataFrame(
        {"MACD-A": [-0.08] * len(states), "SFL-2m": [-0.03] * len(states)},
        index=states.index,
    )
    current = MarketStateV1(0.78, 0.82, 0.16, 0.55, 0.62, 0.66, 0.18)
    decision = choose_model_v1(current, states, returns, risk=1.0)
    assert decision.model == FLAT_MODEL_V1


def test_low_risk_requires_more_confidence_before_leaving_flat():
    states = _states()
    returns = pd.DataFrame(
        {"MACD-A": [0.10] * len(states), "SFL-2m": [0.08] * len(states)},
        index=states.index,
    )
    current = MarketStateV1(0.78, 0.82, 0.16, 0.55, 0.62, 0.66, 0.18)
    conservative = choose_model_v1(current, states, returns, risk=0.0)
    assert conservative.model == FLAT_MODEL_V1
