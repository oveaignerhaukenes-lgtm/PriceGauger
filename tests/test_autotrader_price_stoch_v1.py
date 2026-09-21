from __future__ import annotations

from pathlib import Path

import pandas as pd

from autotrader_price_stoch_v1 import (
    FLAT,
    LONG,
    SHORT,
    PRICE_STOCH_STRATEGY_V1,
    PriceStochConfigV1,
    _stochastic_scout_v1,
    evaluate_price_stoch_row_v1,
)
from autotrader_strategy_catalog_v2 import AUTOTRADER_STRATEGIES_V2, strategy_spec_v2


def _row(
    *,
    fast: float,
    slow: float,
    threshold: float = 0.005,
    slope1: float = 4.0,
    slope3: float = 3.0,
    slope5: float = 2.0,
    macd: float = 0.0,
) -> pd.Series:
    return pd.Series(
        {
            "STOCH_K": 55.0,
            "STOCH_SLOPE_1": slope1,
            "STOCH_SLOPE_3": slope3,
            "STOCH_SLOPE_5": slope5,
            "STOCH_ANGLE_1": 25.0,
            "STOCH_ANGLE_3": 20.0,
            "STOCH_ANGLE_5": 14.0,
            "PRICE_FAST_SLOPE_PCT": fast,
            "PRICE_SLOW_SLOPE_PCT": slow,
            "PRICE_THRESHOLD_PCT": threshold,
            "MACD_SPREAD": macd,
        }
    )


def test_price_confirms_long_even_while_macd_is_still_bearish() -> None:
    decision = evaluate_price_stoch_row_v1(
        _row(fast=0.009, slow=0.005, macd=-0.5),
        current_target=SHORT,
    )
    assert decision.target == LONG
    assert decision.price_direction == LONG
    assert decision.macd_direction == SHORT
    assert decision.state == "PRICE_CONFIRMED_REVERSAL"


def test_gentle_price_downtrend_can_reverse_before_macd_crosses() -> None:
    decision = evaluate_price_stoch_row_v1(
        _row(
            fast=-0.0045,
            slow=-0.0040,
            slope1=-3.0,
            slope3=-2.5,
            slope5=-1.5,
            macd=0.25,
        ),
        current_target=LONG,
    )
    assert decision.target == SHORT
    assert decision.price_direction == SHORT
    assert decision.macd_direction == LONG


def test_stochastic_scout_alone_can_half_parade_but_not_reverse() -> None:
    decision = evaluate_price_stoch_row_v1(
        _row(
            fast=0.0004,
            slow=0.0002,
            slope1=5.0,
            slope3=3.5,
            slope5=2.5,
            macd=-0.2,
        ),
        current_target=SHORT,
    )
    assert decision.stochastic_scout == LONG
    assert decision.price_direction == FLAT
    assert decision.target == FLAT
    assert decision.state == "HALF_PARADE_UP"


def test_stochastic_scout_from_flat_waits_for_price_confirmation() -> None:
    decision = evaluate_price_stoch_row_v1(
        _row(
            fast=0.0002,
            slow=0.0001,
            slope1=5.0,
            slope3=4.0,
            slope5=3.0,
        ),
        current_target=FLAT,
    )
    assert decision.stochastic_scout == LONG
    assert decision.target == FLAT
    assert decision.state == "HALF_PARADE_WAIT"


def test_stochastic_scout_needs_fast_and_three_bar_slope_agreement() -> None:
    scout, alignment = _stochastic_scout_v1(
        slope_1=5.0,
        slope_3=-3.0,
        slope_5=4.0,
        min_slope=1.25,
    )
    assert scout == FLAT
    assert alignment == 0


def test_price_stoch_is_first_class_live_catalog_strategy() -> None:
    keys = {item.key for item in AUTOTRADER_STRATEGIES_V2}
    assert PRICE_STOCH_STRATEGY_V1 in keys
    spec = strategy_spec_v2(PRICE_STOCH_STRATEGY_V1)
    assert spec.can_long is True
    assert spec.can_short is True
    assert "Price + Stoch" in spec.label


def test_live_price_stoch_uses_forming_candle_but_has_no_broker_submit_authority() -> None:
    source = Path("autotrader_price_stoch_live_v1.py").read_text(encoding="utf-8")
    dispatch = Path("autotrader_automanage_dispatch_v2.py").read_text(encoding="utf-8")
    assert "FormingCandleStore" in source
    assert "FORMING_MAX_AGE_SECONDS_V1" in source
    assert "_persist_binary_macd_intent_v1" in source
    assert "PRICE_STOCH_LIVE_STRATEGIES_V1" in dispatch
    assert "run_price_stoch_live_once_v1" in dispatch
    assert "enrollment.strategy_key in PRICE_STOCH_LIVE_STRATEGIES_V1" in dispatch
    lowered = source.lower()
    for forbidden in (
        "trade/v2/orders",
        "session.post(",
        "requests.post(",
        "place_order(",
        "create_order(",
    ):
        assert forbidden not in lowered


def test_strategy_lab_uses_same_price_stoch_core() -> None:
    source = Path("tradingdesk_three_trader_lab_v1.py").read_text(encoding="utf-8")
    chart = Path("tradingdesk_ui/charts/lightweight/three_trader_tv_v1.py").read_text(encoding="utf-8")
    assert 'PRICE_STOCH_NAME = "Price + Stoch"' in source
    assert "replay_price_stoch_v1(bars)" in source
    assert "include_flat=True" in source
    assert '"Price + Stoch": "#ea580c"' in chart
