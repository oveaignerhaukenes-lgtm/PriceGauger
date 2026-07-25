from asset_state_mapping import AssetRecommendation
from combined_direct import build_combined_direct_assessment
from market_interpretation import MarketInterpretation
from technical_regime import TechnicalRegime


def interpretation(*, confidence: float = 0.9, source_quality: float = 0.8) -> MarketInterpretation:
    return MarketInterpretation(
        event_id="event-1",
        cluster_id="cluster-1",
        published_at="2026-07-24T10:00:00+00:00",
        summary="Test event",
        state_deltas={
            "conflict_pressure": 0.5,
            "energy_supply_risk": 0.5,
            "shipping_risk": 0.5,
            "safe_haven_pressure": 0.2,
            "usd_pressure": 0.0,
        },
        novelty=0.8,
        confidence=confidence,
        source_quality=source_quality,
        update_type="NEW_EVENT",
    )


def recommendation(direction: str, strength: int = 80) -> AssetRecommendation:
    return AssetRecommendation(
        asset="Brent",
        direction=direction,
        score=0.8 if direction == "LONG" else -0.8 if direction == "SHORT" else 0.0,
        signal_strength=strength,
        horizon_hours=4,
        rationale=("energy_supply_risk: +0.400",),
    )


def regime(
    bias: str,
    *,
    quality: str = "HIGH",
    interval: int = 10,
) -> TechnicalRegime:
    return TechnicalRegime(
        bias=bias,
        signal_quality=quality,
        regime="Test regime",
        review_interval_minutes=interval,
        review_label=f"Oppdater innen {interval} minutter",
        reversal_risk="MODERAT",
        rationale=("Samlet teknisk bias test.",),
    )


def test_aligned_layers_produce_bullish_combined_assessment():
    result = build_combined_direct_assessment(
        interpretation(),
        recommendation("LONG"),
        regime("BULLISH"),
        technical_sources={"5m": "Saxo", "30m": "Saxo", "1h": "Saxo"},
    )

    assert result.event_bias == "LONG"
    assert result.technical_bias == "BULLISH"
    assert result.alignment == "ALIGNED"
    assert result.combined_bias == "BULLISH"
    assert result.data_quality == "PRIMARY"
    assert result.combined_confidence > 0.7


def test_conflict_is_explicit_and_reduces_confidence():
    aligned = build_combined_direct_assessment(
        interpretation(),
        recommendation("LONG"),
        regime("BULLISH"),
        technical_sources={"5m": "Saxo"},
    )
    conflict = build_combined_direct_assessment(
        interpretation(),
        recommendation("LONG"),
        regime("BEARISH"),
        technical_sources={"5m": "Saxo"},
    )

    assert conflict.alignment == "CONFLICT"
    assert conflict.combined_confidence < aligned.combined_confidence
    assert any("CONFLICT" in reason for reason in conflict.rationale)


def test_insufficient_technical_data_preserves_direct_layer():
    result = build_combined_direct_assessment(
        interpretation(),
        recommendation("SHORT", strength=90),
        regime("NEUTRAL", quality="INSUFFICIENT", interval=15),
        technical_sources={},
    )

    assert result.alignment == "TECHNICAL INSUFFICIENT"
    assert result.combined_bias == "BEARISH"
    assert result.data_quality == "UNKNOWN"
    assert result.review_interval_minutes == 15


def test_yahoo_only_is_marked_as_fallback():
    result = build_combined_direct_assessment(
        interpretation(),
        recommendation("LONG"),
        regime("SLIGHTLY BULLISH", quality="MEDIUM"),
        technical_sources={"5m": "Yahoo Finance", "30m": "Yahoo Finance", "1h": "Yahoo Finance"},
    )

    assert result.data_quality == "FALLBACK"
    assert result.technical_sources == ("Yahoo Finance",)


def test_mixed_saxo_and_yahoo_sources_are_visible():
    result = build_combined_direct_assessment(
        interpretation(),
        recommendation("LONG"),
        regime("BULLISH"),
        technical_sources={"5m": "Saxo", "30m": "Yahoo Finance", "1h": "Saxo"},
    )

    assert result.data_quality == "MIXED"
    assert result.technical_sources == ("Saxo", "Yahoo Finance")
