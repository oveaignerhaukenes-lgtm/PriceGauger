from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import math

from autotrader_macd_supervisor_replay_v1 import (
    SUPERVISOR_WARMUP_1M_ROWS_V1,
    replay_macd_supervisor_v1,
    summarize_macd_supervisor_frame_v1,
)
from canonical_market_bars_v2 import CanonicalMarketBarV2


def _bars(count: int = 1800) -> tuple[CanonicalMarketBarV2, ...]:
    start = datetime(2026, 9, 10, 0, 0, tzinfo=timezone.utc)
    result = []
    for index in range(count):
        # Broad waves plus a slow drift force the supervisor to experience both
        # continuation and propagated reversals after the 30m warmup.
        base = 29000.0 + (index * 0.01) + (80.0 * math.sin(index / 150.0))
        close = base + (12.0 * math.sin(index / 19.0))
        result.append(
            CanonicalMarketBarV2(
                instrument_id=7,
                market_id=7,
                market_name="US Tech 100 NAS · Saxo 4912",
                bar_time=(start + timedelta(minutes=index)).isoformat(),
                open=base,
                high=max(base, close) + 2.0,
                low=min(base, close) - 2.0,
                close=close,
                volume=None,
                quality_flags=1,
            )
        )
    return tuple(result)


def test_supervisor_replay_produces_switches_explanations_and_metrics() -> None:
    frame, switches, summary = replay_macd_supervisor_v1(_bars())
    assert len(frame) == 1800
    assert {"PRICE", "TARGET", "SCORE", "CONFIDENCE", "RETURN_PCT"} <= set(frame.columns)
    assert len(switches) >= 2
    assert summary.switches == len(switches)
    assert -100.0 <= summary.capture_area_pct <= 100.0
    assert 0.0 <= summary.profitable_time_pct <= 100.0
    assert all(item.explanation for item in switches)
    assert all(set(item.spreads) == {1, 2, 5, 10, 15, 30} for item in switches)


def test_supervisor_waits_for_30m_warmup_before_taking_a_side() -> None:
    frame, _, _ = replay_macd_supervisor_v1(_bars())
    warmup = frame.iloc[:SUPERVISOR_WARMUP_1M_ROWS_V1]
    assert (warmup["TARGET"] == 0.0).all()


def test_visible_window_summary_is_independent_of_hidden_warmup_metrics() -> None:
    frame, _, _ = replay_macd_supervisor_v1(_bars())
    visible = frame.iloc[-360:]
    summary = summarize_macd_supervisor_frame_v1(visible)
    assert summary.rows == 360
    assert -100.0 <= summary.capture_area_pct <= 100.0
    assert 0.0 <= summary.win_rate_pct <= 100.0


def test_cost_penalizes_same_supervisor_replay() -> None:
    free, _, _ = replay_macd_supervisor_v1(_bars(), cost_bps_per_leg=0.0)
    costly, _, _ = replay_macd_supervisor_v1(_bars(), cost_bps_per_leg=2.0)
    assert costly["RETURN_PCT"].iloc[-1] < free["RETURN_PCT"].iloc[-1]


def test_supervisor_lab_is_observation_only_and_mounted_as_own_card() -> None:
    source = Path("tradingdesk_macd_supervisor_lab_v1.py").read_text(encoding="utf-8")
    facade = Path("tradingdesk_automanage_panel_v2.py").read_text(encoding="utf-8")
    assert "MACD Supervisor · observasjonslab" in source
    assert "Capture-area" in source
    assert "Beslutninger · traverser skiftene" in source
    assert "render_tradingdesk_macd_supervisor_lab_v1(context)" in facade
    assert "trade/v2/orders" not in source
    assert "request_manual_target_v2" not in source
    assert "switch_live_strategy_v2" not in source
