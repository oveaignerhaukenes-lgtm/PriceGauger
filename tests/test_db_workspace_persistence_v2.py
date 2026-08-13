from __future__ import annotations

from technical_core_v2 import TechnicalBaselineForecast, TechnicalCoreState
from workspace_composer_v2 import AnalysisRecipeV2, CachedLayerOutput, WorkspaceSnapshotV2
from db_workspace_persistence_v2 import (
    DbWorkspacePersistenceV2,
    technical_recipe_uuid,
    analysis_recipe_uuid,
)


def _state() -> TechnicalCoreState:
    return TechnicalCoreState(
        market="Silver",
        as_of="2026-08-14T00:00:00+00:00",
        recipe_version="technical-core-v2.1",
        primary_timeframe="30m",
        trend_state="BULLISH",
        momentum_state="BULLISH",
        volatility_state="NORMAL",
        structure_state="HH_HL",
        score=0.42,
        confidence=0.71,
        snapshots={"30m": {"rsi_14": 63.0, "macd_histogram": 0.12}},
    )


def _baseline(state: TechnicalCoreState | None = None) -> TechnicalBaselineForecast:
    state = state or _state()
    return TechnicalBaselineForecast(
        market=state.market,
        as_of=state.as_of,
        horizon_seconds=3600,
        recipe_version=state.recipe_version,
        direction="BULLISH",
        expected_return=0.004,
        lower_return=-0.002,
        upper_return=0.01,
        confidence=state.confidence,
        path_shape="DRIFT",
        technical_state=state,
    )


def test_recipe_ids_are_deterministic():
    assert technical_recipe_uuid("technical-core-v2.1") == technical_recipe_uuid("technical-core-v2.1")
    recipe = AnalysisRecipeV2(name="ta", version=1, enabled_layers=())
    assert analysis_recipe_uuid(recipe) == analysis_recipe_uuid(recipe)


def test_sqlite_round_trip_preserves_layer_cache(tmp_path):
    db_path = tmp_path / "pg-v2-test.db"
    store = DbWorkspacePersistenceV2(sqlite_path=db_path, force_sqlite=True)
    store.initialize_test_schema()

    market_id = store.ensure_market("Silver", category="metal")
    state = _state()
    baseline = _baseline(state)
    recipe = AnalysisRecipeV2(name="ta-plus-interpreter", version=1, enabled_layers=("technical-interpreter",))

    technical_state_id = store.persist_technical_state(market_id, state)
    analysis_recipe_id = store.persist_analysis_recipe(recipe, state.recipe_version)
    store.persist_baseline_forecast(market_id, technical_state_id, analysis_recipe_id, baseline)

    workspace = WorkspaceSnapshotV2(
        market=state.market,
        as_of=state.as_of,
        technical_state=state,
        technical_baselines={3600: baseline},
    )
    layer = CachedLayerOutput(
        layer_name="technical-interpreter",
        layer_version="technical-interpreter-v2.1",
        input_fingerprint=workspace.fingerprint,
        directional_bias=0.55,
        velocity_modifier=0.2,
        uncertainty_modifier=-0.1,
        reversal_probability=0.2,
        squeeze_probability=0.15,
        confidence=0.78,
        details={"human_summary": "Momentum and volume support continuation."},
    )
    store.persist_layer_output(market_id, state.as_of, layer)

    restored = store.load_layer_outputs(market_id, state.as_of, workspace.fingerprint)
    assert set(restored) == {"technical-interpreter"}
    assert restored["technical-interpreter"].directional_bias == 0.55
    assert restored["technical-interpreter"].details["human_summary"].startswith("Momentum")


def test_wrong_fingerprint_does_not_restore_cached_layers(tmp_path):
    db_path = tmp_path / "pg-v2-test.db"
    store = DbWorkspacePersistenceV2(sqlite_path=db_path, force_sqlite=True)
    store.initialize_test_schema()
    market_id = store.ensure_market("Silver", category="metal")

    layer = CachedLayerOutput(
        layer_name="technical-interpreter",
        layer_version="technical-interpreter-v2.1",
        input_fingerprint="fingerprint-a",
        directional_bias=0.1,
        details={},
    )
    store.persist_layer_output(market_id, "2026-08-14T00:00:00+00:00", layer)

    restored = store.load_layer_outputs(market_id, "2026-08-14T00:00:00+00:00", "fingerprint-b")
    assert restored == {}
