from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from autotrader_shadow_benchmark_v2 import ShadowBenchmarkSeriesV2, ShadowEquityPointV2
from autotrader_shadow_leverage_v2 import LiveLeverageScheduleV2
from autotrader_strategy_series_materializer_v1 import (
    MACD_1M_SERIES_VERSION,
    MACD_30M_SERIES_VERSION,
    _series_points_v1,
    strategy_series_version_v1,
)
from autotrader_strategy_series_store_v1 import strategy_series_key_v1
from autotrader_strategy_catalog_v2 import (
    AI_BASELINE_STRATEGY_V2,
    MACD_1M_FLIP_STRATEGY_V2,
    MACD_FLIP_STRATEGY_V2,
    STRONG_COCKTAIL_STRATEGY_V2,
)


ROOT = Path(__file__).resolve().parents[1]
UTC = timezone.utc


def test_strategy_series_key_is_stable_and_versions_do_not_mix() -> None:
    kwargs = dict(
        account_id="1068427INET",
        uic=4912,
        asset_type="CfdOnIndex",
        instrument_id=77,
        strategy_key=STRONG_COCKTAIL_STRATEGY_V2,
        started_at=datetime(2026, 9, 3, 12, 0, tzinfo=UTC),
    )
    first = strategy_series_key_v1(strategy_version="SC-v1", **kwargs)
    second = strategy_series_key_v1(strategy_version="SC-v1", **kwargs)
    changed = strategy_series_key_v1(strategy_version="SC-v2", **kwargs)
    assert first == second
    assert first != changed


def test_strategy_versions_are_explicit_for_core_strategy_lab_models() -> None:
    assert strategy_series_version_v1(MACD_1M_FLIP_STRATEGY_V2) == MACD_1M_SERIES_VERSION
    assert strategy_series_version_v1(MACD_FLIP_STRATEGY_V2) == MACD_30M_SERIES_VERSION
    assert strategy_series_version_v1(STRONG_COCKTAIL_STRATEGY_V2).startswith("SC-")
    assert "AI-BASELINE" in strategy_series_version_v1(AI_BASELINE_STRATEGY_V2)


def test_series_point_projection_keeps_raw_and_pilot_equivalent_equity() -> None:
    started = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)
    raw = ShadowBenchmarkSeriesV2(
        strategy_key=MACD_1M_FLIP_STRATEGY_V2,
        execution_mode="SHADOW_CONTROL",
        currency="NOK",
        seed_equity=500.0,
        started_at=started,
        points=(
            ShadowEquityPointV2(started, 500.0, "FLAT"),
            ShadowEquityPointV2(datetime(2026, 9, 3, 12, 1, tzinfo=UTC), 505.0, "LONG"),
        ),
    )
    leveraged = ShadowBenchmarkSeriesV2(
        strategy_key=raw.strategy_key,
        execution_mode=raw.execution_mode,
        currency=raw.currency,
        seed_equity=raw.seed_equity,
        started_at=raw.started_at,
        points=(
            ShadowEquityPointV2(started, 500.0, "FLAT"),
            ShadowEquityPointV2(datetime(2026, 9, 3, 12, 1, tzinfo=UTC), 540.0, "LONG"),
        ),
    )
    schedule = LiveLeverageScheduleV2(points=(), fallback_leverage=8.0, source="test")
    projected = _series_points_v1(raw, leveraged, schedule)
    assert len(projected) == 2
    assert projected[-1].equity_1x == pytest.approx(505.0)
    assert projected[-1].return_pct_1x == pytest.approx(1.0)
    assert projected[-1].effective_leverage == pytest.approx(8.0)
    assert projected[-1].equity_pilot_equivalent == pytest.approx(540.0)
    assert projected[-1].return_pct_pilot_equivalent == pytest.approx(8.0)
    assert projected[-1].position_state == "LONG"


def test_common_store_is_one_contract_not_one_table_per_model() -> None:
    source = (ROOT / "autotrader_strategy_series_store_v1.py").read_text(encoding="utf-8")
    assert "pg_v2_strategy_series_points" in source
    assert "strategy_key TEXT NOT NULL" in source
    assert "strategy_version TEXT NOT NULL" in source
    assert "equity_1x DOUBLE PRECISION" in source
    assert "equity_pilot_equivalent DOUBLE PRECISION" in source
    assert "PRIMARY KEY (series_key, observed_at)" in source


def test_worker_materializes_after_ai_context_decision_and_outside_tradingdesk() -> None:
    worker = (ROOT / "worker.py").read_text(encoding="utf-8")
    tradingdesk = (ROOT / "tradingdesk_automanage_panel_v2.py").read_text(encoding="utf-8")
    ai_index = worker.index("run_ai_baseline_shadow_once_v1")
    materialize_index = worker.rindex("materialize_strategy_series_once_v1")
    assert ai_index < materialize_index
    assert "materialize_strategy_series_once_v1" not in tradingdesk
