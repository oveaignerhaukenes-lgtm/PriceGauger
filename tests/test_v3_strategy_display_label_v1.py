from autotrader_v3_registry_v1 import strategy_display_label_v3


def test_regime_histogram_display_label_carries_both_timeframes():
    assert strategy_display_label_v3(
        "macd-regime-histogram","2m","15m"
    ) == "Histogram MACD-R15mS2m"


def test_regular_strategy_display_label_carries_signal_timeframe():
    assert strategy_display_label_v3(
        "macd-histogram","5m","15m"
    ) == "MACD Histogram · 5m"


def test_aen2_display_label_carries_regime_and_signal_timeframes():
    assert strategy_display_label_v3(
        "aen2-sticky-regime","2m","15m"
    ) == "Aen#2 · Sticky R15m/S2m"
