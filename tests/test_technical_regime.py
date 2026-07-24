from technical_analysis import TechnicalReading, TechnicalSnapshot
from technical_regime import build_technical_regime


def snapshot(
    timeframe: str,
    *,
    biases: tuple[str, ...],
    support_distance: float = 2.0,
    resistance_distance: float = 2.0,
    atr_pct: float = 0.1,
    rsi: float = 50.0,
) -> TechnicalSnapshot:
    readings = tuple(
        TechnicalReading(
            label="trend" if index == 0 else "momentum",
            interpretation="test",
            indicator="test",
            timeframe=timeframe,
            value="test",
            bias=bias,
        )
        for index, bias in enumerate(biases)
    )
    return TechnicalSnapshot(
        asset="Silver",
        timeframe=timeframe,
        timestamp="2026-07-24T00:00:00+00:00",
        price=58.0,
        rsi_14=rsi,
        macd=0.1,
        macd_signal=0.0,
        macd_histogram=0.1,
        ema_20=58.0,
        ema_50=57.0,
        atr_14=0.1,
        atr_14_pct=atr_pct,
        volume_ratio_20=1.0,
        support=57.0,
        resistance=59.0,
        distance_to_support_pct=support_distance,
        distance_to_resistance_pct=resistance_distance,
        market_structure="HH_HL",
        readings=readings,
    )


def test_stable_aligned_regime_allows_hourly_review():
    result = build_technical_regime(
        {
            "5m": snapshot("5m", biases=("bullish", "bullish")),
            "30m": snapshot("30m", biases=("bullish", "bullish")),
            "1h": snapshot("1h", biases=("bullish", "bullish")),
        }
    )
    assert result.bias == "BULLISH"
    assert result.review_interval_minutes == 60
    assert result.reversal_risk == "LAV–MODERAT"


def test_conflict_and_near_level_requires_fast_review():
    result = build_technical_regime(
        {
            "5m": snapshot("5m", biases=("bullish", "bullish"), resistance_distance=0.2),
            "30m": snapshot("30m", biases=("bearish", "bearish")),
            "1h": snapshot("1h", biases=("bearish", "bearish")),
        }
    )
    assert result.review_interval_minutes <= 10
    assert result.reversal_risk in {"HØY", "MODERAT–HØY"}


def test_extreme_rsi_increases_monitoring_urgency():
    result = build_technical_regime(
        {
            "5m": snapshot("5m", biases=("bullish",), rsi=74.0),
            "30m": snapshot("30m", biases=("bullish",)),
        }
    )
    assert result.review_interval_minutes <= 30
    assert any("RSI" in line for line in result.rationale)


def test_empty_input_is_explicitly_insufficient():
    result = build_technical_regime({})
    assert result.signal_quality == "INSUFFICIENT"
    assert result.bias == "NEUTRAL"
