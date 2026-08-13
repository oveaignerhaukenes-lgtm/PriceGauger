from technical_core_v2 import TechnicalCoreState
from technical_interpreter_v2 import build_technical_interpreter_payload, validate_technical_interpretation


def _state() -> TechnicalCoreState:
    return TechnicalCoreState(
        market="Silver",
        as_of="2026-08-14T00:00:00+00:00",
        recipe_version="technical-core-v2.1",
        primary_timeframe="30m",
        trend_state="BULLISH",
        momentum_state="BULLISH",
        volatility_state="NORMAL",
        structure_state="HH_HL",
        score=0.42,
        confidence=0.71,
        snapshots={"30m": {"rsi_14": 63.0, "macd_histogram": 0.12, "volume_ratio_20": 1.8}},
    )


def test_payload_contains_only_technical_state_fields():
    payload = build_technical_interpreter_payload(_state())
    assert payload["market"] == "Silver"
    assert payload["technical_recipe"] == "technical-core-v2.1"
    assert "snapshots" in payload
    forbidden = {"news", "macro", "telegram", "regime", "position", "account", "execution"}
    assert forbidden.isdisjoint(payload)


def test_structured_interpretation_is_bounded_and_auditable():
    result = validate_technical_interpretation(
        _state(),
        {
            "directional_bias": "bullish",
            "continuation_probability": 0.72,
            "mean_reversion_probability": 0.28,
            "breakout_probability": 0.66,
            "rejection_probability": 0.34,
            "squeeze_probability": 0.18,
            "confidence": 0.74,
            "emphasis": {"momentum": 0.9, "volume": 0.8, "resistance": 0.45},
            "human_summary": "Sterkt momentum og høyt volum gjør continuation mer sannsynlig enn rejection ved motstand.",
        },
    )
    assert result.directional_bias == "BULLISH"
    assert result.breakout_probability == 0.66
    assert result.source_technical_recipe == "technical-core-v2.1"
    assert "momentum" in result.human_summary.lower()


def test_invalid_probabilities_are_rejected():
    record = {
        "directional_bias": "BULLISH",
        "continuation_probability": 1.2,
        "mean_reversion_probability": 0.2,
        "breakout_probability": 0.7,
        "rejection_probability": 0.3,
        "squeeze_probability": 0.1,
        "confidence": 0.8,
        "emphasis": {},
        "human_summary": "Kort forklaring.",
    }
    try:
        validate_technical_interpretation(_state(), record)
    except ValueError as exc:
        assert "between 0 and 1" in str(exc)
    else:
        raise AssertionError("Expected ValueError")


def test_empty_human_summary_is_rejected():
    record = {
        "directional_bias": "NEUTRAL",
        "continuation_probability": 0.5,
        "mean_reversion_probability": 0.5,
        "breakout_probability": 0.5,
        "rejection_probability": 0.5,
        "squeeze_probability": 0.1,
        "confidence": 0.5,
        "emphasis": {},
        "human_summary": "",
    }
    try:
        validate_technical_interpretation(_state(), record)
    except ValueError as exc:
        assert "human_summary" in str(exc)
    else:
        raise AssertionError("Expected ValueError")
