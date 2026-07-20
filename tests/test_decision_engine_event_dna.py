from __future__ import annotations

import pandas as pd

from decision_engine import build_market_assessment, build_strategy_suggestion
from event_dna import MarketProfile


def _market(prices: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-07-01", periods=len(prices), freq="5min", tz="UTC"),
            "close": prices,
        }
    )


def _profile(**overrides) -> MarketProfile:
    values = {
        "asset": "Brent",
        "sample_size": 6,
        "effective_sample_size": 4.5,
        "positive_share_pct": 83.3,
        "median_1h_pct": 0.7,
        "median_4h_pct": 1.2,
        "median_24h_pct": 2.0,
        "weighted_mean_1h_pct": 0.8,
        "weighted_mean_4h_pct": 1.4,
        "weighted_mean_24h_pct": 2.1,
        "median_max_up_24h_pct": 3.0,
        "median_max_down_24h_pct": -0.6,
        "confidence_pct": 78.0,
        "direction": "LONG",
    }
    values.update(overrides)
    return MarketProfile(**values)


def test_market_profile_overrides_unfiltered_reaction_history() -> None:
    reactions = [
        {
            "asset": "Brent",
            "return_1h_pct": -3.0,
            "return_4h_pct": -4.0,
            "max_down_24h_pct": -6.0,
            "quality_score": 100.0,
        }
        for _ in range(20)
    ]

    assessment = build_market_assessment(
        asset="Brent",
        messages=pd.DataFrame(),
        market=_market([100.0, 100.0, 100.0]),
        intraday_reactions=reactions,
        market_profile=_profile(),
    )

    assert assessment.direction == "LONG"
    assert assessment.expected_move_pct == 1.4
    assert assessment.historical_sample == 6
    assert any("EventDNA-utvalg" in reason for reason in assessment.rationale)
    assert not any("Historisk utvalg for Brent: 20" in reason for reason in assessment.rationale)


def test_small_analogue_sample_forces_no_trade() -> None:
    assessment = build_market_assessment(
        asset="Brent",
        messages=pd.DataFrame(),
        market=_market([100.0, 100.0, 100.0]),
        market_profile=_profile(sample_size=2, effective_sample_size=1.2),
    )
    strategy = build_strategy_suggestion(assessment)

    assert assessment.evidence_grade == "INSUFFICIENT"
    assert strategy.action == "NO TRADE"
    assert strategy.max_leverage == 1.0


def test_profile_expected_move_prefers_weighted_four_hour_return() -> None:
    assessment = build_market_assessment(
        asset="Brent",
        messages=pd.DataFrame(),
        market=_market([100.0, 100.0, 100.0]),
        market_profile=_profile(weighted_mean_4h_pct=-1.1, median_4h_pct=4.0),
    )

    assert assessment.expected_move_pct == -1.1
    assert assessment.direction == "SHORT"
    assert any("Likhetsvektet forventning etter 4 timer: -1.100 %" in reason for reason in assessment.rationale)


def test_profile_falls_back_to_median_when_weighted_values_are_missing() -> None:
    assessment = build_market_assessment(
        asset="Brent",
        messages=pd.DataFrame(),
        market=_market([100.0, 100.0, 100.0]),
        market_profile=_profile(weighted_mean_4h_pct=None, median_4h_pct=0.9),
    )

    assert assessment.expected_move_pct == 0.9
    assert assessment.direction == "LONG"


def test_positive_analogue_expectation_cannot_silently_flip_short() -> None:
    neutral_context = build_market_assessment(
        asset="Brent",
        messages=pd.DataFrame(),
        market=_market([100.0, 100.0, 100.0]),
        market_profile=_profile(weighted_mean_4h_pct=0.5),
    )
    conflicting_context = build_market_assessment(
        asset="Brent",
        messages=pd.DataFrame(),
        market=_market([120.0, 105.0, 90.0]),
        market_profile=_profile(weighted_mean_4h_pct=0.5),
    )

    assert conflicting_context.expected_move_pct == 0.5
    assert conflicting_context.direction == "LONG"
    assert conflicting_context.confidence_pct < neutral_context.confidence_pct
    assert any("peker motsatt" in reason for reason in conflicting_context.rationale)
    assert any("Komponenter:" in reason for reason in conflicting_context.rationale)


def test_negative_analogue_expectation_cannot_silently_flip_long() -> None:
    assessment = build_market_assessment(
        asset="Brent",
        messages=pd.DataFrame(),
        market=_market([90.0, 105.0, 120.0]),
        market_profile=_profile(
            weighted_mean_4h_pct=-0.6,
            positive_share_pct=20.0,
            direction="SHORT",
        ),
    )

    assert assessment.expected_move_pct == -0.6
    assert assessment.direction == "SHORT"
    assert any("peker motsatt" in reason for reason in assessment.rationale)
