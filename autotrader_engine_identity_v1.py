from __future__ import annotations

"""Engine-neutral identity helpers for shared UI/read models."""

ENGINE_V2 = "V2"
ENGINE_V3 = "V3"

V3_STRATEGY_KEYS = frozenset({
    "macd-trailing-v1",
    "macd-histogram-v1",
    "macd-stoch-v1",
})

def engine_for_strategy_key_v1(strategy_key: str) -> str:
    return ENGINE_V3 if str(strategy_key).strip() in V3_STRATEGY_KEYS else ENGINE_V2

def enrollment_engine_v1(enrollment) -> str:
    return engine_for_strategy_key_v1(str(enrollment.strategy_key))
