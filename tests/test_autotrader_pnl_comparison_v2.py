from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from autotrader_pnl_chart_v2 import build_automanager_pnl_figure_v2
from autotrader_pnl_comparison_v2 import (
    AutoManagerPnlComparisonV2,
    LiveRealizedPnlEventV2,
    build_live_realized_pnl_curve_v2,
)
from autotrader_shadow_benchmark_v2 import ShadowBenchmarkSeriesV2, ShadowEquityPointV2
from autotrader_strategy_catalog_v2 import MACD_LONG_FLAT_STRATEGY_V2


START = datetime(2026, 8, 30, 18, 0, tzinfo=timezone.utc)


def test_live_curve_is_settled_only_and_normalized_to_isolated_seed() -> None:
    curve = build_live_realized_pnl_curve_v2(
        seed_equity=500.0,
        started_at=START,
        as_of=START + timedelta(hours=2),
        events=(
            LiveRealizedPnlEventV2(START + timedelta(minutes=90), -10.0),
            LiveRealizedPnlEventV2(START + timedelta(minutes=30), 25.0),
        ),
    )

    assert [item.cumulative_pnl for item in curve] == [0.0, 25.0, 15.0, 15.0]
    assert [item.return_pct for item in curve] == pytest.approx([0.0, 5.0, 3.0, 3.0])
    assert curve[-1].occurred_at == START + timedelta(hours=2)


def test_pnl_figure_uses_separate_live_and_paper_panels() -> None:
    live = build_live_realized_pnl_curve_v2(
        seed_equity=500.0,
        started_at=START,
        as_of=START + timedelta(hours=1),
        events=(LiveRealizedPnlEventV2(START + timedelta(minutes=45), 5.0),),
    )
    paper = ShadowBenchmarkSeriesV2(
        strategy_key=MACD_LONG_FLAT_STRATEGY_V2,
        execution_mode="LIVE_MANAGE",
        currency="NOK",
        seed_equity=500.0,
        started_at=START,
        points=(
            ShadowEquityPointV2(START + timedelta(minutes=30), 500.0, "LONG"),
            ShadowEquityPointV2(START + timedelta(minutes=60), 510.0, "LONG"),
        ),
    )
    comparison = AutoManagerPnlComparisonV2(
        pilot_key="pilot",
        currency="NOK",
        seed_equity=500.0,
        started_at=START,
        as_of=START + timedelta(hours=1),
        live_realized=live,
        paper_series=(paper,),
    )

    figure = build_automanager_pnl_figure_v2(comparison)
    traces = {trace.name: trace for trace in figure.data}
    assert traces["LIVE · realisert Saxo"].yaxis == "y"
    assert traces["LIVE · realisert Saxo"].line.shape == "hv"
    assert traces["Paper · 30m MACD long/flat · defensive"].yaxis == "y2"
    assert tuple(traces["Paper · 30m MACD long/flat · defensive"].y) == pytest.approx((0.0, 2.0))
