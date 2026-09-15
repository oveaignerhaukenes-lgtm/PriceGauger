from pathlib import Path

from autotrader_overseer_performance_v1 import (
    FLAT_MODEL_V1,
    ModelPerformanceV1,
    choose_performance_model_v1,
)


def model(name, ret, dd=-0.02, positive=.6, stability=.7):
    return ModelPerformanceV1(name, ret, dd, positive, stability)


def test_overseer_selects_model_that_is_working_now():
    decision = choose_performance_model_v1([model("macd-a-v1", -.3), model("macd-15m-flip-control-shadow-v1", .8)])
    assert decision.model == "macd-15m-flip-control-shadow-v1"


def test_overseer_uses_flat_when_no_model_has_edge():
    decision = choose_performance_model_v1([model("a", -.2), model("b", -.1)])
    assert decision.model == FLAT_MODEL_V1


def test_hysteresis_prevents_small_challenger_ping_pong():
    decision = choose_performance_model_v1(
        [model("incumbent", .50), model("challenger", .54)],
        incumbent="incumbent",
        challenger_margin=.10,
    )
    assert decision.model == "incumbent"


def test_overseer_is_catalogued_live_capable_but_not_auto_switching():
    catalog = Path("autotrader_strategy_catalog_v2.py").read_text(encoding="utf-8")
    dispatch = Path("autotrader_automanage_dispatch_v2.py").read_text(encoding="utf-8")
    assert 'OVERSEER_PERFORMANCE_STRATEGY_KEY_V1' in catalog
    assert 'OVERSEER_PERFORMANCE_STRATEGY_KEY_V1' in dispatch
    assert 'run_overseer_live_once_v1' in dispatch
    assert 'auto_switch' not in dispatch.lower()


def test_strategy_lab_materializer_contains_overseer_series():
    materializer = Path("autotrader_strategy_series_materializer_v1.py").read_text(encoding="utf-8")
    assert "load_overseer_performance_series_v1" in materializer
    assert "OVERSEER_PERFORMANCE_STRATEGY_KEY_V1" in materializer
