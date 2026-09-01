from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from autotrader_pnl_chart_v2 import build_automanager_pnl_figure_v2
from autotrader_pnl_comparison_v2 import (
    AutoManagerPnlComparisonV2,
    LiveRealizedPnlEventV2,
    LiveStrategyEpochV2,
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


def test_live_curve_keeps_strategy_attribution_across_pilot_epochs() -> None:
    curve = build_live_realized_pnl_curve_v2(
        seed_equity=500.0,
        started_at=START,
        as_of=START + timedelta(hours=3),
        initial_pilot_key="classic-pilot",
        initial_strategy_key=MACD_LONG_FLAT_STRATEGY_V2,
        as_of_pilot_key="mtf-pilot",
        as_of_strategy_key="macd-mtf-30-10-5-long-short-v1",
        events=(
            LiveRealizedPnlEventV2(
                START + timedelta(hours=1),
                10.0,
                pilot_key="classic-pilot",
                strategy_key=MACD_LONG_FLAT_STRATEGY_V2,
            ),
            LiveRealizedPnlEventV2(
                START + timedelta(hours=2),
                -2.0,
                pilot_key="mtf-pilot",
                strategy_key="macd-mtf-30-10-5-long-short-v1",
            ),
        ),
    )
    assert [item.cumulative_pnl for item in curve] == pytest.approx([0.0, 10.0, 8.0, 8.0])
    assert curve[1].pilot_key == "classic-pilot"
    assert curve[2].pilot_key == "mtf-pilot"
    assert curve[-1].strategy_key == "macd-mtf-30-10-5-long-short-v1"


def test_pnl_figure_uses_linked_timeline_range_tools_and_strategy_epochs() -> None:
    live = build_live_realized_pnl_curve_v2(
        seed_equity=500.0,
        started_at=START,
        as_of=START + timedelta(hours=1),
        initial_pilot_key="pilot",
        initial_strategy_key=MACD_LONG_FLAT_STRATEGY_V2,
        as_of_pilot_key="pilot",
        as_of_strategy_key=MACD_LONG_FLAT_STRATEGY_V2,
        events=(
            LiveRealizedPnlEventV2(
                START + timedelta(minutes=45),
                5.0,
                pilot_key="pilot",
                strategy_key=MACD_LONG_FLAT_STRATEGY_V2,
            ),
        ),
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
        product_key="acct:4912:CfdOnIndex:7",
        currency="NOK",
        seed_equity=500.0,
        started_at=START,
        as_of=START + timedelta(hours=1),
        live_realized=live,
        live_epochs=(
            LiveStrategyEpochV2(
                pilot_key="pilot",
                strategy_key=MACD_LONG_FLAT_STRATEGY_V2,
                started_at=START,
                ended_at=None,
            ),
        ),
        paper_series=(paper,),
    )

    figure = build_automanager_pnl_figure_v2(comparison)
    traces = {trace.name: trace for trace in figure.data}
    assert traces["LIVE · realisert Saxo"].yaxis == "y"
    assert traces["LIVE · realisert Saxo"].line.shape == "hv"
    assert traces["Paper · 30m MACD long/flat · defensive"].yaxis == "y2"
    assert tuple(traces["Paper · 30m MACD long/flat · defensive"].y) == pytest.approx((0.0, 2.0))
    assert figure.layout.xaxis.matches == "x2"
    assert figure.layout.xaxis2.rangeslider.visible is True
    assert [button.label for button in figure.layout.xaxis2.rangeselector.buttons] == [
        "1t", "4t", "12t", "1d", "3d", "Alt"
    ]
    assert figure.layout.uirevision.startswith("AutoManagerPnlProduct:acct:4912:CfdOnIndex:7")
    assert len(figure.layout.shapes) >= 3  # strategy epoch + zero lines for both panels
    assert any(annotation.text == "30m MACD long/flat · defensive" for annotation in figure.layout.annotations)
