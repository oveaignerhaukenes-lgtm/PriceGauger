from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import math

import pytest

from autotrader_hybrid_replay_v1 import replay_hybrid_models_v1
from canonical_market_bars_v2 import CanonicalMarketBarV2


def _bars(count: int = 360) -> tuple[CanonicalMarketBarV2, ...]:
    start = datetime(2026, 9, 10, 0, 0, tzinfo=timezone.utc)
    result = []
    for index in range(count):
        base = 29000.0 + (index * 0.08) + (12.0 * math.sin(index / 9.0))
        close = base + (2.0 * math.sin(index / 3.0))
        result.append(
            CanonicalMarketBarV2(
                instrument_id=7,
                market_id=7,
                market_name="US Tech 100 NAS · Saxo 4912",
                bar_time=(start + timedelta(minutes=index)).isoformat(),
                open=base,
                high=max(base, close) + 1.5,
                low=min(base, close) - 1.5,
                close=close,
                volume=None,
                quality_flags=1,
            )
        )
    return tuple(result)


def test_hybrid_replay_produces_component_and_combined_curves() -> None:
    frame, summary = replay_hybrid_models_v1(_bars())
    assert len(frame) == 360
    assert {"MACD2", "MACD2-10", "MACD2-S", "MACD-A", "HYBRID", "HYBRID_SCORE", "PRICE"} <= set(frame.columns)
    assert summary.rows == 360
    assert summary.switches["HYBRID"] >= 1
    assert frame["HYBRID_SCORE"].abs().max() <= 1.0 + 1e-9


def test_100_percent_macd2_hybrid_matches_macd2_curve() -> None:
    frame, _ = replay_hybrid_models_v1(
        _bars(),
        weights={"MACD2": 100, "MACD2-10": 0, "MACD2-S": 0, "MACD-A": 0},
    )
    assert frame["HYBRID"].iloc[-1] == pytest.approx(frame["MACD2"].iloc[-1])


def test_replay_cost_penalizes_turnover() -> None:
    free, _ = replay_hybrid_models_v1(_bars(), cost_bps_per_leg=0.0)
    costly, _ = replay_hybrid_models_v1(_bars(), cost_bps_per_leg=2.0)
    assert costly["HYBRID"].iloc[-1] < free["HYBRID"].iloc[-1]


def test_hybrid_ui_is_test_only_and_does_not_submit_orders() -> None:
    source = Path("tradingdesk_hybrid_lab_v1.py").read_text(encoding="utf-8")
    facade = Path("tradingdesk_automanage_panel_v2.py").read_text(encoding="utf-8")
    assert "render_tradingdesk_hybrid_lab_v1(context)" in facade
    assert "pg_v2_hybrid_lab_config" in source
    assert "replay_hybrid_models_v1" in source
    assert "trade/v2/orders" not in source
    assert "request_manual_target_v2" not in source
    assert "switch_live_strategy_v2" not in source
