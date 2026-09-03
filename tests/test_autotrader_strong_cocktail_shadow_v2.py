from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import autotrader_strong_cocktail_shadow_v2 as strong
from autotrader_shadow_benchmark_v2 import STATE_FLAT, STATE_LONG, STATE_SHORT


NOW = datetime(2026, 9, 3, 7, 30, tzinfo=timezone.utc)


def _evidence(
    *,
    cross: str | None = None,
    spread1: float = 0.2,
    velocity1: float = 0.2,
    move3: float = 0.5,
    move5: float = 0.6,
    efficiency: float = 0.7,
    structure: str | None = None,
    activity: float = 0.0,
    range_ratio: float = 1.0,
    break_direction: str | None = None,
    shock_direction: str | None = None,
    whipsaw: bool = False,
    data_gap: bool = False,
    spread5: float = 0.3,
    spread10: float = 0.3,
    spread15: float = 0.3,
    spread30: float = 0.3,
) -> strong.StrongCocktailEvidenceV1:
    return strong.StrongCocktailEvidenceV1(
        action_at=NOW,
        price=100.0,
        cross_1m=cross,
        spread_1m=spread1,
        velocity_1m_atr=velocity1,
        move_3m_atr1=move3,
        move_5m_atr1=move5,
        efficiency_5m=efficiency,
        structure_direction=structure,
        activity_z=activity,
        range_ratio_1m=range_ratio,
        break_direction=break_direction,
        shock_direction=shock_direction,
        whipsaw=whipsaw,
        data_gap=data_gap,
        spread_5m=spread5,
        spread_10m=spread10,
        spread_15m=spread15,
        spread_30m=spread30,
    )


def test_price_and_1m_velocity_can_flatten_before_cross_or_slow_confirmation() -> None:
    evidence = _evidence(
        cross=None,
        spread1=0.1,
        velocity1=-0.3,
        move3=-0.9,
        move5=-1.0,
        spread5=0.4,
        spread10=0.5,
        spread15=0.6,
        spread30=0.7,
    )
    assert strong.strong_cocktail_target_v1(STATE_LONG, evidence) == STATE_FLAT


def test_1m_cross_can_enter_without_waiting_for_higher_timeframe_cross() -> None:
    evidence = _evidence(
        cross=STATE_LONG,
        spread1=0.2,
        velocity1=0.25,
        move3=0.45,
        move5=0.6,
        structure=STATE_LONG,
        spread5=-0.1,
        spread10=0.1,
        spread15=0.1,
        spread30=0.1,
    )
    assert strong.strong_cocktail_target_v1(STATE_FLAT, evidence) == STATE_LONG


def test_counter_cross_can_exit_then_persistent_fast_move_reenters_without_second_cross() -> None:
    exit_evidence = _evidence(
        cross=STATE_SHORT,
        spread1=-0.12,
        velocity1=-0.18,
        move3=-0.45,
        move5=-0.55,
        efficiency=0.62,
        spread5=0.3,
        spread10=0.3,
        spread15=0.3,
        spread30=0.3,
    )
    assert strong.strong_cocktail_target_v1(STATE_LONG, exit_evidence) == STATE_FLAT

    continuation = _evidence(
        cross=None,
        spread1=-0.22,
        velocity1=-0.20,
        move3=-0.72,
        move5=-0.90,
        efficiency=0.72,
        structure=STATE_SHORT,
        range_ratio=1.18,
        spread5=0.3,
        spread10=0.3,
        spread15=0.3,
        spread30=0.3,
    )
    assert strong.strong_cocktail_target_v1(STATE_FLAT, continuation) == STATE_SHORT


def test_continuation_entry_is_symmetric_for_long_moves() -> None:
    continuation = _evidence(
        cross=None,
        spread1=0.18,
        velocity1=0.16,
        move3=0.42,
        move5=0.62,
        efficiency=0.68,
        break_direction=STATE_LONG,
        spread5=0.2,
        spread10=-0.1,
        spread15=0.1,
        spread30=0.1,
    )
    assert strong.strong_cocktail_target_v1(STATE_FLAT, continuation) == STATE_LONG


def test_slow_opposition_raises_continuation_bar_but_does_not_become_sequential_gate() -> None:
    weak_against_slow_context = _evidence(
        cross=None,
        spread1=-0.18,
        velocity1=-0.12,
        move3=-0.45,
        move5=-0.62,
        efficiency=0.68,
        range_ratio=1.10,
        spread5=0.3,
        spread10=0.3,
        spread15=0.3,
        spread30=0.3,
    )
    assert strong.strong_cocktail_target_v1(STATE_FLAT, weak_against_slow_context) == STATE_FLAT

    price_confirmed_against_slow_context = _evidence(
        cross=None,
        spread1=-0.25,
        velocity1=-0.20,
        move3=-0.72,
        move5=-0.90,
        efficiency=0.74,
        structure=STATE_SHORT,
        range_ratio=1.18,
        spread5=0.3,
        spread10=0.3,
        spread15=0.3,
        spread30=0.3,
    )
    assert strong.strong_cocktail_target_v1(STATE_FLAT, price_confirmed_against_slow_context) == STATE_SHORT


def test_heavy_slow_opposition_blocks_ordinary_1m_entry() -> None:
    evidence = _evidence(
        cross=STATE_LONG,
        spread1=0.2,
        velocity1=0.2,
        move3=0.4,
        move5=0.6,
        efficiency=0.4,
        spread5=-0.4,
        spread10=-0.4,
        spread15=-0.4,
        spread30=-0.4,
    )
    assert strong.strong_cocktail_target_v1(STATE_FLAT, evidence) == STATE_FLAT


def test_strong_price_event_can_override_slow_opposition() -> None:
    evidence = _evidence(
        cross=STATE_LONG,
        spread1=0.3,
        velocity1=0.4,
        move3=1.3,
        move5=1.6,
        efficiency=0.85,
        structure=STATE_LONG,
        activity=1.4,
        spread5=-0.4,
        spread10=-0.4,
        spread15=-0.4,
        spread30=-0.4,
    )
    assert strong.strong_cocktail_target_v1(STATE_FLAT, evidence) == STATE_LONG


def test_whipsaw_stays_flat_without_strong_escape() -> None:
    evidence = _evidence(
        cross=STATE_LONG,
        spread1=0.1,
        velocity1=0.1,
        move3=0.3,
        move5=0.4,
        efficiency=0.5,
        whipsaw=True,
    )
    assert strong.strong_cocktail_target_v1(STATE_FLAT, evidence) == STATE_FLAT


def test_simple_1m_control_only_flips_on_contiguous_cross() -> None:
    assert strong.macd_1m_control_target_v1(
        STATE_FLAT,
        cross_1m=STATE_LONG,
        data_gap=False,
    ) == STATE_LONG
    assert strong.macd_1m_control_target_v1(
        STATE_LONG,
        cross_1m=STATE_SHORT,
        data_gap=False,
    ) == STATE_SHORT
    assert strong.macd_1m_control_target_v1(
        STATE_SHORT,
        cross_1m=STATE_LONG,
        data_gap=True,
    ) == STATE_SHORT


def test_strong_cocktail_is_shadow_only_and_reporting_wires_both_series() -> None:
    source = Path("autotrader_strong_cocktail_shadow_v2.py").read_text(encoding="utf-8")
    comparison = Path("autotrader_pnl_comparison_v2.py").read_text(encoding="utf-8")
    chart = Path("autotrader_pnl_chart_v2.py").read_text(encoding="utf-8")

    assert "trade/v2/orders" not in source
    assert "_post_once" not in source
    assert "pg_v2_autotrader_execution_requests" not in source
    assert "live_open" not in source
    assert "live_close" not in source
    assert "load_strong_cocktail_comparison_series_v1" in comparison
    assert "SHADOW_CONTROL" in chart
    assert "Strong Cocktail · 1m event + MTF context" in chart
    assert "1m MACD flip · control" in chart


def test_strong_cocktail_contract_is_documented_as_hypothesis_not_live_authority() -> None:
    text = Path("docs/STRONG_COCKTAIL_V1.md").read_text(encoding="utf-8")
    assert "SHADOW ONLY" in text
    assert "1m MACD" in text
    assert "higher horizons qualify confidence" in text
    assert "hypothesis" in text.lower()
    assert "must beat" not in text.lower()
