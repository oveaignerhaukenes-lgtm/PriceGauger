from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from autotrader_price_macd_v1 import (
    FLAT,
    LONG,
    SHORT,
    evaluate_price_macd_row_v1,
)
from autotrader_strategy_catalog_v2 import strategy_spec_v2
from autotrader_strategy_family_v1 import (
    FAMILY_MACD_STRATEGY_V1,
    FAMILY_MACD_V1,
    FAMILY_PRICE_MACD_STRATEGY_V1,
    FAMILY_PRICE_MACD_V1,
    FAMILY_PRICE_STOCH_V1,
    TIMEFRAME_PRESETS_V1,
    family_strategy_key_v1,
    validate_timeframe_minutes_v1,
)


def _row(
    *,
    fast: float,
    slow: float,
    threshold: float = 0.005,
    macd_spread: float = 0.2,
    macd_direction: int = LONG,
    macd_cross: int = FLAT,
) -> pd.Series:
    return pd.Series(
        {
            "PRICE_FAST_SLOPE_PCT": fast,
            "PRICE_SLOW_SLOPE_PCT": slow,
            "PRICE_THRESHOLD_PCT": threshold,
            "MACD_SPREAD": macd_spread,
            "MACD_DIRECTION": macd_direction,
            "MACD_CROSS": macd_cross,
        }
    )


def test_price_authority_holds_long_through_bearish_macd_cross() -> None:
    decision = evaluate_price_macd_row_v1(
        _row(
            fast=0.010,
            slow=0.007,
            macd_spread=-0.1,
            macd_direction=SHORT,
            macd_cross=SHORT,
        ),
        current_target=LONG,
    )
    assert decision.price_direction == LONG
    assert decision.macd_cross == SHORT
    assert decision.target == LONG
    assert decision.state == "PRICE_AUTHORITY"


def test_price_downtrend_can_reverse_before_macd_crosses() -> None:
    decision = evaluate_price_macd_row_v1(
        _row(
            fast=-0.009,
            slow=-0.006,
            macd_spread=0.2,
            macd_direction=LONG,
            macd_cross=FLAT,
        ),
        current_target=LONG,
    )
    assert decision.price_direction == SHORT
    assert decision.macd_direction == LONG
    assert decision.target == SHORT
    assert decision.state == "PRICE_AUTHORITY"


def test_macd_cross_is_fallback_when_price_is_neutral() -> None:
    decision = evaluate_price_macd_row_v1(
        _row(
            fast=0.0001,
            slow=0.0001,
            macd_spread=-0.05,
            macd_direction=SHORT,
            macd_cross=SHORT,
        ),
        current_target=LONG,
    )
    assert decision.price_direction == FLAT
    assert decision.target == SHORT
    assert decision.state == "MACD_FALLBACK"


def test_old_macd_state_does_not_bootstrap_a_flat_position() -> None:
    decision = evaluate_price_macd_row_v1(
        _row(
            fast=0.0,
            slow=0.0,
            macd_spread=0.2,
            macd_direction=LONG,
            macd_cross=FLAT,
        ),
        current_target=FLAT,
    )
    assert decision.target == FLAT
    assert decision.state == "WAIT_FRESH"


@pytest.mark.parametrize("minutes", [1, 2, 5, 7, 10, 15, 30, 37, 60, 240])
def test_family_timeframe_accepts_presets_and_custom_minutes(minutes: int) -> None:
    assert validate_timeframe_minutes_v1(minutes) == minutes


@pytest.mark.parametrize("minutes", [0, -1, 241])
def test_family_timeframe_rejects_unsafe_bounds(minutes: int) -> None:
    with pytest.raises(ValueError):
        validate_timeframe_minutes_v1(minutes)


def test_family_catalog_has_generic_live_strategy_keys() -> None:
    assert family_strategy_key_v1(FAMILY_MACD_V1) == FAMILY_MACD_STRATEGY_V1
    assert family_strategy_key_v1(FAMILY_PRICE_MACD_V1) == FAMILY_PRICE_MACD_STRATEGY_V1
    assert strategy_spec_v2(FAMILY_MACD_STRATEGY_V1).can_long is True
    assert strategy_spec_v2(FAMILY_MACD_STRATEGY_V1).can_short is True
    assert strategy_spec_v2(FAMILY_PRICE_MACD_STRATEGY_V1).can_long is True
    assert strategy_spec_v2(FAMILY_PRICE_MACD_STRATEGY_V1).can_short is True
    assert TIMEFRAME_PRESETS_V1 == (1, 2, 5, 10, 15, 30, 60)


def test_family_ui_exposes_family_timeframe_custom_and_sim_live_modes() -> None:
    source = Path("tradingdesk_strategy_family_ui_v1.py").read_text(encoding="utf-8")
    simple = Path("tradingdesk_automanager_simple_v1.py").read_text(encoding="utf-8")
    assert '"Familie"' in source
    assert '"Tidsperiode"' in source
    assert '"Egen tidsperiode (min)"' in source
    assert 'SIM_MODE_V1 = "SIM"' in source
    assert 'LIVE_MODE_V1 = "LIVE"' in source
    assert "save_family_sim_config_v1" in source
    assert "switch_live_strategy_v2" in source
    assert "reconfigure_live_family_v1" in source
    assert "render_strategy_family_builder_v1(" in simple
    assert "**Legacy / enkeltstrategi**" in simple


def test_family_parameter_change_is_execution_safe_and_resets_signal_state() -> None:
    source = Path("autotrader_strategy_family_v1.py").read_text(encoding="utf-8")
    assert "status IN ('SUBMITTING','ORDER_ACCEPTED','UNCERTAIN')" in source
    assert "FAMILY_PARAMETER_CHANGE" in source
    assert "DELETE FROM pg_v2_autotrader_fast_live_state" in source


def test_family_sim_is_persistent_not_browser_only() -> None:
    source = Path("autotrader_strategy_family_v1.py").read_text(encoding="utf-8")
    ui = Path("tradingdesk_strategy_family_ui_v1.py").read_text(encoding="utf-8")
    lab = Path("tradingdesk_three_trader_lab_v1.py").read_text(encoding="utf-8")
    assert "pg_v2_autotrader_strategy_family_sim_config" in source
    assert "load_family_sim_config_v1" in ui
    assert "load_sim_family_selection_v1" in lab
    assert "replay_strategy_family_v1(" in lab


def test_price_macd_live_has_no_direct_broker_submit_authority() -> None:
    source = Path("autotrader_price_macd_live_v1.py").read_text(encoding="utf-8").lower()
    assert "_persist_binary_macd_intent_v1" in source
    assert "family_price_macd_v1" in source
    for forbidden in (
        "trade/v2/orders",
        "session.post(",
        "requests.post(",
        "place_order(",
        "create_order(",
    ):
        assert forbidden not in source


def test_dispatch_routes_both_parameterized_families() -> None:
    source = Path("autotrader_automanage_dispatch_v2.py").read_text(encoding="utf-8")
    assert "FAMILY_MACD_STRATEGY_V1" in source
    assert "PRICE_MACD_LIVE_STRATEGIES_V1" in source
    assert "run_price_macd_live_once_v1" in source


def test_price_stoch_family_is_explicitly_one_minute_in_v1_ui() -> None:
    source = Path("tradingdesk_strategy_family_ui_v1.py").read_text(encoding="utf-8")
    assert "family == FAMILY_PRICE_STOCH_V1" in source
    assert "Price + Stoch v1 bruker foreløpig 1m" in source
