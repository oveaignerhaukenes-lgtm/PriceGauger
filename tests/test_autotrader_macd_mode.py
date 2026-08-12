from __future__ import annotations

from trading_desk_indicators import IndicatorPoint, TechnicalIndicators
from autotrader_macd_mode import crossover_from_indicators


def _indicators(macd: list[float], signal: list[float]) -> TechnicalIndicators:
    macd_points = tuple(IndicatorPoint(bar_time=index, value=value) for index, value in enumerate(macd))
    signal_points = tuple(IndicatorPoint(bar_time=index, value=value) for index, value in enumerate(signal))
    return TechnicalIndicators(macd=macd_points, macd_signal=signal_points)


def test_bullish_cross_creates_one_buy_intent() -> None:
    intent = crossover_from_indicators(
        _indicators([-1.0, 0.2], [0.0, 0.0]),
        market="Gold",
        amount=2.0,
    )

    assert intent is not None
    assert intent.side == "Buy"
    assert intent.amount == 2.0
    assert intent.direction == "BULLISH"
    assert intent.bar_time == 1


def test_bearish_cross_creates_one_sell_intent() -> None:
    intent = crossover_from_indicators(
        _indicators([0.4, -0.1], [0.0, 0.0]),
        market="Silver",
        amount=1.0,
    )

    assert intent is not None
    assert intent.side == "Sell"
    assert intent.direction == "BEARISH"


def test_staying_above_signal_does_not_repeat_intent() -> None:
    intent = crossover_from_indicators(
        _indicators([0.2, 0.4], [0.0, 0.0]),
        market="Brent",
        amount=1.0,
    )

    assert intent is None


def test_staying_below_signal_does_not_repeat_intent() -> None:
    intent = crossover_from_indicators(
        _indicators([-0.2, -0.4], [0.0, 0.0]),
        market="Brent",
        amount=1.0,
    )

    assert intent is None


def test_event_key_is_stable_for_same_cross() -> None:
    first = crossover_from_indicators(
        _indicators([-0.2, 0.4], [0.0, 0.0]),
        market="Gold",
        amount=1.0,
    )
    second = crossover_from_indicators(
        _indicators([-0.2, 0.4], [0.0, 0.0]),
        market="Gold",
        amount=5.0,
    )

    assert first is not None and second is not None
    assert first.event_key == second.event_key


def test_invalid_amount_is_rejected() -> None:
    try:
        crossover_from_indicators(
            _indicators([-0.2, 0.4], [0.0, 0.0]),
            market="Gold",
            amount=0.0,
        )
    except ValueError as exc:
        assert "positive" in str(exc)
    else:
        raise AssertionError("expected ValueError")
