from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import autotrader_cocktail_mode_1_shadow_v2 as cocktail


NOW = datetime(2026, 9, 2, 0, 15, tzinfo=timezone.utc)


class _CaptureDb:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def execute(self, sql: str, params=()):
        packed = tuple(params)
        assert sql.count("?") == len(packed), (
            f"Cocktail SQL placeholder mismatch: {sql.count('?')} placeholders "
            f"for {len(packed)} parameters"
        )
        self.calls.append((sql, packed))
        return self

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def _clock(tf: int) -> cocktail.MacdClockV1:
    return cocktail.MacdClockV1(
        timeframe_minutes=tf,
        macd=0.1,
        signal=0.0,
        spread=0.1,
        previous_spread=-0.1,
        previous2_spread=-0.2,
        velocity_atr=0.02,
        acceleration_atr=0.0,
        cross=cocktail.CROSS_UP,
        cross_observed_at=NOW,
        cross_estimated_at=NOW,
    )


def _snapshot() -> cocktail.CocktailSnapshotV1:
    return cocktail.CocktailSnapshotV1(
        action_at=NOW,
        market_id=1,
        instrument_id=7,
        market_name="US Tech 100 NAS · Saxo 4912",
        price=100.0,
        clock_5m=_clock(5),
        clock_10m=_clock(10),
        clock_15m=_clock(15),
        clock_30m=_clock(30),
        atr_5m=5.0,
        atr_10m=10.0,
        atr_30m=30.0,
        range_ratio_1m=1.5,
        activity_z=2.1,
        activity_source="range_proxy",
        efficiency_5m=0.8,
        efficiency_30m=0.5,
        displacement_5m_atr5=0.6,
        displacement_30m_atr10=0.7,
        support=90.0,
        resistance=99.0,
        break_direction=cocktail.POSITION_LONG,
        break_distance_atr5=0.2,
        low_activity=False,
        divergent_5_10=False,
        shock_direction=cocktail.POSITION_LONG,
        trend_lock_direction=None,
        whipsaw=False,
        escape_direction=cocktail.POSITION_LONG,
        recent_fast_crosses_30m=1,
        data_gap=False,
    )


def test_persistence_sql_placeholder_count_matches_bound_parameters(monkeypatch) -> None:
    db = _CaptureDb()
    monkeypatch.setattr(cocktail, "connect", lambda: db)
    prior = cocktail.CocktailStateV1(
        instrument_id=7,
        market_id=1,
        market_name="US Tech 100 NAS · Saxo 4912",
    )
    snapshot = _snapshot()
    decision = cocktail.CocktailDecisionV1(
        action=cocktail.ACTION_OPEN_LONG,
        target_position=cocktail.POSITION_LONG,
        mode=cocktail.MODE_SHOCK,
        pending_direction=None,
        pending_confirmation_tf=None,
        reason="contract test",
    )
    updated = cocktail.apply_cocktail_decision_v1(prior, snapshot, decision)

    cocktail._persist_sample_and_state_v1(
        prior=prior,
        snapshot=snapshot,
        decision=decision,
        updated=updated,
    )

    assert len(db.calls) == 2
    assert "pg_v2_autotrader_cocktail_mode_1_samples" in db.calls[0][0]
    assert "pg_v2_autotrader_cocktail_mode_1_state" in db.calls[1][0]


def test_worker_runs_cocktail_as_separate_shadow_thread() -> None:
    source = Path("realtime_worker.py").read_text(encoding="utf-8")
    assert "run_cocktail_mode_1_shadow_forever_v1" in source
    assert "PRICEGAUGER_AUTOTRADER_COCKTAIL_MODE_1_SHADOW_SECONDS" in source
    assert "_start_autotrader_cocktail_mode_1_shadow" in source
    assert "canonical 1m clock with adaptive 5/10/15/30m MACD" in source


def test_reporting_appends_adaptive_shadow_without_live_authority() -> None:
    comparison = Path("autotrader_pnl_comparison_v2.py").read_text(encoding="utf-8")
    chart = Path("autotrader_pnl_chart_v2.py").read_text(encoding="utf-8")
    catalog = Path("autotrader_strategy_catalog_v2.py").read_text(encoding="utf-8")
    assert "load_cocktail_shadow_series_v1" in comparison
    assert '"SHADOW_ADAPTIVE"' in chart
    assert "strategy_display_label_v2" in chart
    assert 'COCKTAIL_MODE_1_SHADOW_STRATEGY_V2 = "cocktail-mode-1-shadow-v1"' in catalog
    # Cocktail Mode #1 itself remains shadow-only even though Strong Cocktail is now live-capable.
    live_tuple = catalog.split("AUTOTRADER_STRATEGIES_V2 = (", 1)[1].split(")", 1)[0]
    assert "COCKTAIL_MODE_1" not in live_tuple


def test_model_contract_is_documented_as_cross_time_shadow_only() -> None:
    text = Path("docs/COCKTAIL_MODE_1_V1.md").read_text(encoding="utf-8")
    assert "MACD cross time" in text
    assert "SHADOW ONLY" in text
    assert "NORMAL" in text
    assert "SHOCK" in text
    assert "TREND_LOCK" in text
    assert "WHIPSAW" in text
    assert "CLOSE -> confirmed Saxo FLAT -> OPEN" in text
    assert "gross" in text
