from __future__ import annotations

from context_snapshot_store_v2 import ContextSnapshotStoreV2
from context_snapshot_v2 import CONTEXT_CONTRACT_VERSION, FRESH, ContextSnapshotV2, ContextTargetStateV2
from parallel_forecast_runtime_v2 import record_parallel_experiments_v2, resolve_parallel_outcomes_v2
from runtime_technical_producer_v2 import ProducedTechnicalRuntimeV2
from technical_core_v2 import TechnicalBaselineForecast, TechnicalCoreState


def _produced() -> ProducedTechnicalRuntimeV2:
    state = TechnicalCoreState(
        market="GOLD",
        as_of="2026-08-17T00:00:00+00:00",
        recipe_version="technical-core-v2.1",
        primary_timeframe="30m",
        trend_state="BULLISH",
        momentum_state="BULLISH",
        volatility_state="NORMAL",
        structure_state="BULLISH",
        score=0.5,
        confidence=0.8,
        snapshots={},
    )
    baseline = TechnicalBaselineForecast(
        market="GOLD",
        as_of=state.as_of,
        horizon_seconds=60,
        recipe_version=state.recipe_version,
        direction="BULLISH",
        expected_return=0.01,
        lower_return=0.0,
        upper_return=0.02,
        confidence=0.8,
        path_shape="TREND",
        technical_state=state,
    )
    return ProducedTechnicalRuntimeV2(
        market="GOLD", as_of=state.as_of, technical_state=state, baselines={60: baseline}
    )


def _context() -> ContextSnapshotV2:
    return ContextSnapshotV2(
        snapshot_id="ctx-1",
        as_of="2026-08-17T00:00:00+00:00",
        contract_version=CONTEXT_CONTRACT_VERSION,
        engine_version="test-context",
        scope_key="global",
        freshness_status=FRESH,
        coverage_start="2026-08-16T23:00:00+00:00",
        coverage_end="2026-08-17T00:00:00+00:00",
        evidence=(),
        targets=(
            ContextTargetStateV2(
                target_key="GOLD",
                directional_bias=0.5,
                confidence=0.8,
                novelty=0.5,
                event_risk=0.4,
            ),
        ),
    )


def test_no_context_creates_no_benchmark(tmp_path):
    attempted, inserted = record_parallel_experiments_v2(
        _produced(), db_path=str(tmp_path / "pg.db")
    )
    assert (attempted, inserted) == (0, 0)


def test_experiment_creation_is_idempotent(tmp_path):
    db_path = str(tmp_path / "pg.db")
    assert ContextSnapshotStoreV2(db_path).save_if_material_change(_context()) is True

    assert record_parallel_experiments_v2(_produced(), db_path=db_path) == (1, 1)
    assert record_parallel_experiments_v2(_produced(), db_path=db_path) == (1, 0)


def test_matured_experiment_is_resolved_once(tmp_path):
    db_path = str(tmp_path / "pg.db")
    ContextSnapshotStoreV2(db_path).save_if_material_change(_context())
    record_parallel_experiments_v2(_produced(), db_path=db_path)

    class History:
        def load_range(self, **kwargs):
            return [
                ("2026-08-17T00:00:00+00:00", 100.0),
                ("2026-08-17T00:01:00+00:00", 101.0),
            ]

    history = History()
    assert resolve_parallel_outcomes_v2(history_store=history, db_path=db_path) == 1
    assert resolve_parallel_outcomes_v2(history_store=history, db_path=db_path) == 0
