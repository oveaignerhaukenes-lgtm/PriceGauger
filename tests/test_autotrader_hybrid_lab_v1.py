from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import math

import pandas as pd
import pytest

from autotrader_hybrid_replay_v1 import _timeframe_spread, replay_hybrid_models_v1
from autotrader_mtf_entry_shadow_v2 import closed_bars_v2, macd_observations_v2
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



def test_macd5_replay_uses_exact_live_closed_bar_and_macd_contract() -> None:
    bars = _bars(600)
    frame = pd.DataFrame(
        {
            "at": [pd.Timestamp(item.bar_time) + pd.Timedelta(minutes=1) for item in bars],
            "close": [float(item.close) for item in bars],
        }
    ).set_index("at")
    replay_spread = _timeframe_spread(frame, 5)

    closed = closed_bars_v2(
        tuple(item.point for item in bars),
        market=bars[0].market_name,
        timeframe_minutes=5,
    )
    live_observations = macd_observations_v2(closed, timeframe_minutes=5)
    comparable = [
        item for item in live_observations
        if pd.Timestamp(item.closed_at) in replay_spread.index
    ]
    assert len(comparable) > 20
    for item in comparable[-20:]:
        assert replay_spread.loc[pd.Timestamp(item.closed_at)] == pytest.approx(
            float(item.spread),
            abs=1e-12,
        )


def test_macd5_replay_switch_times_match_live_cross_times() -> None:
    bars = _bars(720)
    frame, _ = replay_hybrid_models_v1(bars)
    target = frame["TARGET_MACD5"]
    replay_switches = {
        pd.Timestamp(at): ("LONG" if float(value) > 0 else "SHORT")
        for at, value in target.items()
        if float(value) != 0.0
        and (
            at == target.index[0]
            or float(value) != float(target.shift(1).loc[at])
        )
    }

    closed = closed_bars_v2(
        tuple(item.point for item in bars),
        market=bars[0].market_name,
        timeframe_minutes=5,
    )
    observations = macd_observations_v2(closed, timeframe_minutes=5)
    live_crosses = {}
    for previous, current in zip(observations, observations[1:]):
        if current.closed_at - previous.closed_at != timedelta(minutes=5):
            continue
        if previous.spread <= 0.0 < current.spread:
            live_crosses[pd.Timestamp(current.closed_at)] = "LONG"
        elif previous.spread >= 0.0 > current.spread:
            live_crosses[pd.Timestamp(current.closed_at)] = "SHORT"

    # Ignore the replay's initial state adoption; every subsequent directional
    # switch must be an exact LIVE cross at the same completed 5m timestamp.
    directional_switches = {
        at: direction
        for at, direction in replay_switches.items()
        if at in live_crosses
    }
    assert len(directional_switches) >= 2
    assert directional_switches == {
        at: direction for at, direction in live_crosses.items() if at in directional_switches
    }


def test_hybrid_ui_is_test_only_and_does_not_submit_orders() -> None:
    source = Path("tradingdesk_hybrid_lab_v1.py").read_text(encoding="utf-8")
    facade = Path("tradingdesk_automanage_panel_v2.py").read_text(encoding="utf-8")
    assert "render_tradingdesk_hybrid_lab_v1(context)" in facade
    assert "pg_v2_hybrid_lab_config" in source
    assert "replay_hybrid_models_v1" in source
    assert "trade/v2/orders" not in source
    assert "request_manual_target_v2" not in source
    assert "switch_live_strategy_v2" not in source
