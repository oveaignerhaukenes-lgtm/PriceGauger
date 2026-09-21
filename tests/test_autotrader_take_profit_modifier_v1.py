from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from autotrader_take_profit_modifier_v1 import (
    TakeProfitConfigV1,
    apply_take_profit_replay_v1,
    evaluate_take_profit_v1,
)


def test_relative_giveback_uses_fraction_of_peak_profit_not_price_points() -> None:
    config = TakeProfitConfigV1(
        enabled=True,
        giveback_pct=10.0,
        min_peak_profit_pct=0.10,
        reentry_cooldown_seconds=30,
    )
    hold = evaluate_take_profit_v1(
        current_pnl_pct=0.91,
        previous_high_water_pct=1.00,
        config=config,
    )
    assert hold.armed is True
    assert hold.floor_pct == pytest.approx(0.90)
    assert hold.triggered is False

    exit_now = evaluate_take_profit_v1(
        current_pnl_pct=0.89,
        previous_high_water_pct=1.00,
        config=config,
    )
    assert exit_now.floor_pct == pytest.approx(0.90)
    assert exit_now.triggered is True


def test_take_profit_does_not_arm_before_user_selected_minimum_peak() -> None:
    decision = evaluate_take_profit_v1(
        current_pnl_pct=0.30,
        previous_high_water_pct=0.40,
        config=TakeProfitConfigV1(
            enabled=True,
            giveback_pct=5.0,
            min_peak_profit_pct=0.50,
            reentry_cooldown_seconds=0,
        ),
    )
    assert decision.high_water_pct == pytest.approx(0.40)
    assert decision.armed is False
    assert decision.floor_pct is None
    assert decision.triggered is False


def test_replay_takes_profit_and_latches_flat_until_base_target_changes() -> None:
    frame = pd.DataFrame(
        {
            "PRICE": [100.00, 100.50, 101.00, 100.89, 100.95, 100.80, 100.60],
            "TARGET": [1, 1, 1, 1, 1, -1, -1],
        },
        index=pd.date_range("2026-09-21T00:00:00Z", periods=7, freq="min"),
    )
    result = apply_take_profit_replay_v1(
        frame,
        giveback_pct=10.0,
        min_peak_profit_pct=0.10,
    )

    assert list(result["TARGET"]) == [1.0, 1.0, 1.0, 0.0, 0.0, -1.0, -1.0]
    assert result["TAKE_PROFIT_REASON"].iloc[3] == "take_profit"
    assert result["TAKE_PROFIT_REASON"].iloc[4] == "take_profit_latched"
    assert result["TAKE_PROFIT_PEAK_PCT"].iloc[2] == pytest.approx(1.0)
    assert result["TAKE_PROFIT_FLOOR_PCT"].iloc[2] == pytest.approx(0.9)


def test_replay_works_for_short_profit_symmetrically() -> None:
    frame = pd.DataFrame(
        {
            "PRICE": [100.0, 99.5, 99.0, 99.12],
            "TARGET": [-1, -1, -1, -1],
        },
        index=pd.date_range("2026-09-21T00:00:00Z", periods=4, freq="min"),
    )
    result = apply_take_profit_replay_v1(
        frame,
        giveback_pct=10.0,
        min_peak_profit_pct=0.10,
    )
    assert list(result["TARGET"]) == [-1.0, -1.0, -1.0, 0.0]


def test_invalid_giveback_is_rejected() -> None:
    with pytest.raises(ValueError):
        evaluate_take_profit_v1(
            current_pnl_pct=1.0,
            previous_high_water_pct=1.0,
            config=TakeProfitConfigV1(enabled=True, giveback_pct=0.0),
        )
    with pytest.raises(ValueError):
        evaluate_take_profit_v1(
            current_pnl_pct=1.0,
            previous_high_water_pct=1.0,
            config=TakeProfitConfigV1(enabled=True, giveback_pct=100.0),
        )


def test_live_modifier_uses_durable_flat_intent_without_broker_submit_authority() -> None:
    source = Path("autotrader_take_profit_modifier_v1.py").read_text(encoding="utf-8").lower()
    assert "_persist_binary_macd_intent_v1" in source
    assert "desired_direction=direction_flat" in source
    assert "ambiguous_execution_statuses_v1" in source
    assert "take_profit_off" in source
    for forbidden in (
        "trade/v2/orders",
        "session.post(",
        "requests.post(",
        "place_order(",
        "create_order(",
    ):
        assert forbidden not in source


def test_fast_managed_risk_path_and_dispatcher_wire_generic_modifier() -> None:
    risk = Path("autotrader_risk_control_v2.py").read_text(encoding="utf-8")
    dispatch = Path("autotrader_automanage_dispatch_v2.py").read_text(encoding="utf-8")
    assert "run_take_profit_observations_v1(tuple(managed_observations))" in risk
    assert "take_profit_reentry_blocked_v1" in dispatch
    assert "TAKE_PROFIT re-entry cooldown" in dispatch


def test_tradingdesk_exposes_user_selected_giveback_and_arm_threshold() -> None:
    source = Path("tradingdesk_automanager_simple_v1.py").read_text(encoding="utf-8")
    assert "**X + TakeProfit**" in source
    assert "Tillatt tilbakegang av peak-profit (%)" in source
    assert "Aktiver først etter gevinst ≥ (%)" in source
    assert "Re-entry pause etter TakeProfit (sek)" in source
    assert "save_take_profit_config_v1" in source


def test_strategy_lab_wraps_arbitrary_selected_base() -> None:
    source = Path("tradingdesk_three_trader_lab_v1.py").read_text(encoding="utf-8")
    assert 'TAKE_PROFIT_NAME = "X + TakeProfit"' in source
    assert '"TakeProfit base (X)"' in source
    assert "apply_take_profit_replay_v1(" in source
    assert "base_frames[tp_base]" in source
