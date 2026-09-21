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


def test_price_macd_live_uses_forming_price_but_closed_macd_context() -> None:
    source = Path("autotrader_price_macd_live_v1.py").read_text(encoding="utf-8")
    assert "_live_bars_and_action_v1(" in source
    assert "macd_bars=eligible" in source


def test_reconfigure_ensures_fast_runtime_schema_before_state_delete() -> None:
    source = Path("autotrader_strategy_family_v1.py").read_text(encoding="utf-8")
    ensure_pos = source.index("ensure_fast_live_schema_v2()", source.index("def reconfigure_live_family_v1"))
    delete_pos = source.index("DELETE FROM pg_v2_autotrader_fast_live_state", source.index("def reconfigure_live_family_v1"))
    assert ensure_pos < delete_pos


def test_family_sim_can_be_takeprofit_base_only_when_available() -> None:
    source = Path("tradingdesk_three_trader_lab_v1.py").read_text(encoding="utf-8")
    assert "tp_base_options = tuple(" in source
    assert "item != FAMILY_SIM_NAME or family_sim_selection is not None" in source
    assert "base_frames[FAMILY_SIM_NAME] = family_sim_frame" in source


def test_takeprofit_modifier_is_carried_across_family_live_switch() -> None:
    source = Path("tradingdesk_strategy_family_ui_v1.py").read_text(encoding="utf-8")
    assert "take_profit_config = load_take_profit_config_v1(enrollment.pilot_key)" in source
    assert "save_take_profit_config_v1(" in source
    assert "target_enrollment.pilot_key" in source

def test_custom_macd_family_timeframe_reaches_live_execution_clock() -> None:
    source = Path("autotrader_macd_timeframe_live_v1.py").read_text(encoding="utf-8")
    start = source.index("def run_macd_timeframe_live_once_v1")
    runtime = source[start:]
    assert "enrollment.strategy_key == FAMILY_MACD_STRATEGY_V1" in runtime
    assert "load_strategy_family_config_v1(" in runtime
    assert "minutes = int(family_config.timeframe_minutes)" in runtime
    assert "_timeframe_clock_v1(tuple(bars), timeframe_minutes=minutes)" in runtime


def test_custom_price_macd_timeframe_reaches_both_sim_and_live_cores() -> None:
    live = Path("autotrader_price_macd_live_v1.py").read_text(encoding="utf-8")
    replay = Path("autotrader_family_replay_v1.py").read_text(encoding="utf-8")

    assert "timeframe_minutes = int(family_config.timeframe_minutes)" in live
    assert "build_price_macd_features_v1(" in live
    assert "timeframe_minutes=timeframe_minutes" in live
    assert "macd_bars=eligible" in live

    assert "return replay_price_macd_v1(items, timeframe_minutes=minutes)" in replay


def test_family_ui_supports_sim_live_or_both_without_hidden_activation() -> None:
    source = Path("tradingdesk_strategy_family_ui_v1.py").read_text(encoding="utf-8")
    assert 'RUN_MODES_V1 = (SIM_MODE_V1, LIVE_MODE_V1)' in source
    assert 'st.multiselect(' in source
    assert '"Aktiver i"' in source
    assert "if SIM_MODE_V1 in modes:" in source
    assert "if LIVE_MODE_V1 in modes:" in source
    assert "Ingen endring skjer før du trykker Bruk." in source


def test_family_timeframe_change_cannot_mutate_ambiguous_execution() -> None:
    source = Path("autotrader_strategy_family_v1.py").read_text(encoding="utf-8")
    runtime_start = source.index("def reconfigure_live_family_v1")
    runtime = source[runtime_start:]
    inflight = runtime.index("status IN ('SUBMITTING','ORDER_ACCEPTED','UNCERTAIN')")
    supersede = runtime.index("FAMILY_PARAMETER_CHANGE")
    reset = runtime.index("DELETE FROM pg_v2_autotrader_fast_live_state")
    persist = runtime.index("INSERT INTO pg_v2_autotrader_strategy_family_config")
    assert inflight < supersede < reset < persist


def test_family_ui_preserves_takeprofit_across_live_family_switch() -> None:
    source = Path("tradingdesk_strategy_family_ui_v1.py").read_text(encoding="utf-8")
    switch = source.index("switch_live_strategy_v2(")
    capture = source.rindex("take_profit_config = load_take_profit_config_v1(", 0, switch)
    restore = source.index("save_take_profit_config_v1(", switch)
    assert capture < switch < restore


def test_price_macd_core_matches_price_first_contract() -> None:
    source = Path("autotrader_price_macd_v1.py").read_text(encoding="utf-8")
    evaluate = source[source.index("def evaluate_price_macd_row_v1"):]
    price_branch = evaluate.index("if price_direction in (LONG, SHORT):")
    macd_branch = evaluate.index("elif macd_cross in (LONG, SHORT):")
    assert price_branch < macd_branch
    assert 'state = "PRICE_AUTHORITY"' in evaluate
    assert 'state = "MACD_FALLBACK"' in evaluate
