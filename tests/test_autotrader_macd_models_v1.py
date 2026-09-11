from __future__ import annotations

from pathlib import Path

import pytest

from autotrader_macd_binary_execution_v1 import SIMPLE_BINARY_MACD_STRATEGIES_V1
from autotrader_macd_models_live_v1 import (
    MACD2_10_STRATEGY_V1,
    MACD2_S_STRATEGY_V1,
    MACD_A_STRATEGY_V1,
    MACD_MODEL_LIVE_STRATEGIES_V1,
)
from autotrader_macd_models_v1 import (
    LONG,
    SHORT,
    adaptive_timeframe_v1,
    macd2_10_target_v1,
    macd2_stochastic_score_v1,
    macd2_stochastic_target_v1,
    stochastic_direction_score_v1,
    weighted_model_target_v1,
)
from autotrader_strategy_catalog_v2 import AUTOTRADER_STRATEGIES_V2, strategy_spec_v2


def test_macd2_10_uses_10m_only_as_regime_filter() -> None:
    assert macd2_10_target_v1(1.0, 0.5, current=SHORT) == LONG
    assert macd2_10_target_v1(-1.0, -0.5, current=LONG) == SHORT
    assert macd2_10_target_v1(1.0, -0.5, current=SHORT) == SHORT
    assert macd2_10_target_v1(-1.0, 0.5, current=LONG) == LONG


def test_stochastic_is_a_modifier_not_a_direction_controller() -> None:
    aligned = macd2_stochastic_score_v1(spread_2m=1.0, stochastic_score=1.0)
    opposed_cross = macd2_stochastic_score_v1(spread_2m=1.0, stochastic_score=-1.0)
    opposed_direction = macd2_stochastic_score_v1(spread_2m=1.0, stochastic_score=-0.6)
    assert aligned == pytest.approx(1.0)
    assert opposed_cross == pytest.approx(0.6)
    assert opposed_direction == pytest.approx(0.68)
    assert macd2_stochastic_target_v1(spread_2m=1.0, stochastic_score=1.0, current=SHORT) == LONG
    # A fresh opposite stochastic K/D cross can defer the flip once.
    assert macd2_stochastic_target_v1(spread_2m=1.0, stochastic_score=-1.0, current=SHORT) == SHORT
    # Persistent opposite direction cannot become a standing veto over MACD2.
    assert macd2_stochastic_target_v1(spread_2m=1.0, stochastic_score=-0.6, current=SHORT) == LONG


def test_stochastic_direction_prefers_kd_cross_then_direction() -> None:
    assert stochastic_direction_score_v1(previous_k=40, previous_d=45, current_k=50, current_d=48) == 1.0
    assert stochastic_direction_score_v1(previous_k=60, previous_d=55, current_k=50, current_d=52) == -1.0
    assert stochastic_direction_score_v1(previous_k=40, previous_d=35, current_k=45, current_d=40) == 0.6


def test_adaptive_timeframe_favors_micro_edge_then_noise_filter() -> None:
    assert adaptive_timeframe_v1(micro_edge=0.8, noise=0.3) == 1
    assert adaptive_timeframe_v1(micro_edge=0.2, noise=0.8) == 5
    assert adaptive_timeframe_v1(micro_edge=0.5, noise=0.5) == 2


def test_weighted_models_resolve_to_one_broker_target() -> None:
    decision = weighted_model_target_v1(
        {"MACD2": 1.0, "MACD2-S": 0.6, "MACD2-10": -1.0},
        {"MACD2": 50, "MACD2-S": 30, "MACD2-10": 20},
        current=SHORT,
    )
    assert decision.target == LONG
    assert decision.score == pytest.approx(0.48)
    assert sum(weight for _, _, weight in decision.components) == pytest.approx(1.0)


def test_weighted_models_hold_current_inside_disagreement_band() -> None:
    decision = weighted_model_target_v1(
        {"a": 1.0, "b": -1.0},
        {"a": 50, "b": 50},
        current=LONG,
        threshold=0.10,
    )
    assert decision.target == LONG
    assert decision.score == pytest.approx(0.0)


def test_weighted_models_require_a_positive_weight() -> None:
    with pytest.raises(ValueError):
        weighted_model_target_v1({"a": 1.0}, {"a": 0.0}, current=LONG)


def test_new_models_are_compact_live_catalog_choices() -> None:
    keys = {item.key for item in AUTOTRADER_STRATEGIES_V2}
    assert MACD_MODEL_LIVE_STRATEGIES_V1 == {
        MACD2_10_STRATEGY_V1,
        MACD2_S_STRATEGY_V1,
        MACD_A_STRATEGY_V1,
    }
    assert MACD_MODEL_LIVE_STRATEGIES_V1 <= keys
    assert strategy_spec_v2(MACD2_10_STRATEGY_V1).label == "MACD2-10"
    assert strategy_spec_v2(MACD2_S_STRATEGY_V1).label == "MACD2-S"
    assert strategy_spec_v2(MACD_A_STRATEGY_V1).label == "MACD-A"


def test_new_models_keep_existing_hardened_execution_path() -> None:
    runtime = Path("autotrader_macd_models_live_v1.py").read_text(encoding="utf-8")
    dispatch = Path("autotrader_automanage_dispatch_v2.py").read_text(encoding="utf-8")
    assert MACD_MODEL_LIVE_STRATEGIES_V1 <= SIMPLE_BINARY_MACD_STRATEGIES_V1
    assert "_persist_binary_macd_intent_v1" in runtime
    assert "MACD_MODEL_LIVE_STRATEGIES_V1" in dispatch
    assert "run_macd_model_live_once_v1" in dispatch
    assert "trade/v2/orders" not in runtime
    assert "place_order(" not in runtime
