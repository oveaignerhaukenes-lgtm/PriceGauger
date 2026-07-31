from __future__ import annotations

import math

from state_runtime_service import market_impulse_score


def test_market_impulse_preserves_strength_differences():
    scores = {
        "Brent": market_impulse_score("Brent", 0.05),
        "DXY": market_impulse_score("DXY", 0.01),
        "Gold": market_impulse_score("Gold", 0.05),
        "Natural Gas": market_impulse_score("Natural Gas", 0.19),
        "Silver": market_impulse_score("Silver", 0.02),
    }

    assert scores["Natural Gas"] > scores["Gold"] > scores["Brent"] > scores["DXY"] > scores["Silver"]
    assert 0.55 < scores["Natural Gas"] < 0.75
    assert scores["Silver"] < 0.15


def test_market_impulse_is_symmetric_and_bounded():
    for market in ("Brent", "Gold", "Silver", "DXY", "Natural Gas"):
        positive = market_impulse_score(market, 0.1)
        negative = market_impulse_score(market, -0.1)
        assert math.isclose(negative, -positive)
        assert -1.0 <= negative <= 0.0 <= positive <= 1.0


def test_zero_impulse_is_neutral():
    assert market_impulse_score("Brent", 0.0) == 0.0
