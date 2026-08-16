from __future__ import annotations

import inspect

import holistic_composer_v1
from context_snapshot_v2 import (
    FRESH,
    STALE,
    ContextSnapshotV2,
    ContextTargetStateV2,
    build_context_snapshot_v2,
)
from holistic_composer_v1 import compose_holistic_forecast_v1
from technical_core_v2 import TechnicalBaselineForecast, TechnicalCoreState


def _technical() -> TechnicalBaselineForecast:
    state = TechnicalCoreState(
        market="Silver",
        as_of="2026-08-17T10:00:00+00:00",
        recipe_version="technical-core-v2.1",
        primary_timeframe="30m",
        trend_state="BULLISH",
        momentum_state="BULLISH",
        volatility_state="NORMAL",
        structure_state="HH_HL",
        score=0.4,
        confidence=0.72,
        snapshots={"30m": {"rsi_14": 62.0}},
    )
    return TechnicalBaselineForecast(
        market=state.market,
        as_of=state.as_of,
        horizon_seconds=3600,
        recipe_version=state.recipe_version,
        direction="BULLISH",
        expected_return=0.004,
        lower_return=-0.002,
        upper_return=0.010,
        confidence=state.confidence,
        path_shape="DRIFT",
        technical_state=state,
    )


def _context(*, freshness: str = FRESH, target_key: str = "Silver", bias: float = 0.8) -> ContextSnapshotV2:
    return build_context_snapshot_v2(
        as_of="2026-08-17T10:01:00+00:00",
        engine_version="context-adapter-v2-v1|flow=test",
        scope_key="global",
        freshness_status=freshness,
        evidence=(),
        targets=(
            ContextTargetStateV2(
                target_key=target_key,
                directional_bias=bias,
                confidence=0.75,
                novelty=0.8,
                event_risk=0.6,
            ),
        ),
        regime_label="risk-on",
    )


def test_fresh_matching_context_refines_baseline_and_preserves_provenance():
    technical = _technical()
    context = _context()

    result = compose_holistic_forecast_v1(technical=technical, context=context)

    assert result.context_applied is True
    assert result.baseline_return == technical.expected_return
    assert result.composed_return > technical.expected_return
    assert result.upper_return - result.lower_return > technical.upper_return - technical.lower_return
    assert result.provenance.technical_recipe == technical.recipe_version
    assert result.provenance.context_snapshot_id == context.snapshot_id
    assert result.provenance.context_fingerprint == context.state_fingerprint
    assert result.provenance.context_target_key == "Silver"


def test_stale_context_is_visible_but_cannot_modify_technical_baseline():
    technical = _technical()
    context = _context(freshness=STALE)

    result = compose_holistic_forecast_v1(technical=technical, context=context)

    assert result.context_applied is False
    assert result.composed_return == technical.expected_return
    assert result.lower_return == technical.lower_return
    assert result.upper_return == technical.upper_return
    assert result.provenance.context_freshness == STALE


def test_missing_market_target_cannot_modify_technical_baseline():
    technical = _technical()
    result = compose_holistic_forecast_v1(
        technical=technical,
        context=_context(target_key="Gold"),
    )

    assert result.context_applied is False
    assert result.composed_return == technical.expected_return
    assert result.provenance.context_target_key == ""


def test_opposing_context_adjustment_is_bounded_and_does_not_replace_baseline():
    technical = _technical()
    result = compose_holistic_forecast_v1(
        technical=technical,
        context=_context(bias=-1.0),
    )

    assert result.context_applied is True
    assert result.composed_return < technical.expected_return
    assert result.composed_return > technical.lower_return
    assert result.baseline_return == technical.expected_return


def test_composer_has_no_llm_legacy_or_execution_authority():
    source = inspect.getsource(holistic_composer_v1)
    executable = "\n".join(
        line for line in source.splitlines()
        if not line.lstrip().startswith(("#", '"""', "'''"))
    )
    forbidden = (
        "OpenAI",
        "openai",
        "state_runtime_pipeline",
        "process_flow_snapshot",
        "DecisionState",
        "AutoTrader",
        "place_order",
        "position_state",
        "account_state",
    )
    for token in forbidden:
        assert token not in executable
