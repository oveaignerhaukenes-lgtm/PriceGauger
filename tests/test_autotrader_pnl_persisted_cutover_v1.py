from __future__ import annotations

from pathlib import Path

from autotrader_pnl_comparison_v2 import (
    PAPER_SCALE_PILOT_EQUIVALENT,
    PAPER_SCALE_RAW_1X,
    AutoManagerPnlComparisonV2,
)
from autotrader_shadow_benchmark_v2 import ShadowBenchmarkSeriesV2, ShadowEquityPointV2
from autotrader_pnl_comparison_v2 import LiveRealizedPnlPointV2
from datetime import datetime, timezone


ROOT = Path(__file__).resolve().parents[1]
UTC = timezone.utc


def _comparison(scale: str) -> AutoManagerPnlComparisonV2:
    started = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)
    series = ShadowBenchmarkSeriesV2(
        strategy_key="macd-1m-flip-control-v1",
        execution_mode="SHADOW_CONTROL",
        currency="NOK",
        seed_equity=500.0,
        started_at=started,
        points=(ShadowEquityPointV2(started, 500.0, "FLAT"),),
    )
    live = (LiveRealizedPnlPointV2(started, 0.0, 0.0),)
    return AutoManagerPnlComparisonV2(
        pilot_key="pilot",
        product_key="acct:4912:CfdOnIndex:77",
        currency="NOK",
        seed_equity=500.0,
        started_at=started,
        as_of=started,
        live_realized=live,
        live_epochs=(),
        paper_series=(series,),
        paper_scale=scale,
    )


def test_comparison_scale_contract_preserves_legacy_default() -> None:
    persisted = _comparison(PAPER_SCALE_PILOT_EQUIVALENT)
    raw = _comparison(PAPER_SCALE_RAW_1X)
    assert persisted.paper_scale == PAPER_SCALE_PILOT_EQUIVALENT
    assert raw.paper_scale == PAPER_SCALE_RAW_1X


def test_public_ui_loader_reads_persisted_series_and_replay_is_explicit_bridge() -> None:
    comparison = (ROOT / "autotrader_pnl_comparison_v2.py").read_text(encoding="utf-8")
    materializer = (ROOT / "autotrader_strategy_series_materializer_v1.py").read_text(encoding="utf-8")
    read_model = (ROOT / "tradingdesk_automanage_panel_legacy_v2.py").read_text(encoding="utf-8")
    facade = (ROOT / "tradingdesk_automanage_panel_v2.py").read_text(encoding="utf-8")

    public_start = comparison.index("def load_automanager_pnl_comparison_v2(")
    replay_start = comparison.index("def replay_automanager_pnl_comparison_v2(")
    public_body = comparison[public_start:replay_start]
    assert "load_persisted_strategy_series_v1(" in public_body
    assert "load_shadow_benchmark_series_exact_anchor_v2(" not in public_body
    assert "there is deliberately no hidden fallback" in public_body

    assert "replay_automanager_pnl_comparison_v2" in materializer
    assert "load_automanager_pnl_comparison_v2" not in materializer
    assert "load_automanager_pnl_comparison_v2(tuple(group))" in read_model
    assert "render_tradingdesk_automanage_pnl_chart_v2" in facade


def test_chart_does_not_apply_leverage_twice_to_persisted_series() -> None:
    chart = (ROOT / "autotrader_pnl_chart_v2.py").read_text(encoding="utf-8")
    persisted_branch = chart.index("if comparison.paper_scale == PAPER_SCALE_PILOT_EQUIVALENT:")
    legacy_branch = chart.index("try:\n        schedule = _leverage_schedule(comparison)", persisted_branch)
    persisted_body = chart[persisted_branch:legacy_branch]
    assert "return comparison.paper_series" in persisted_body
    assert "apply_schedule_to_series_v2" not in persisted_body
    assert "apply_schedule_to_series_v2" in chart[legacy_branch:]
