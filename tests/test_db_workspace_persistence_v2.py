from __future__ import annotations

import json
from contextlib import contextmanager

import db_workspace_persistence_v2 as persistence
from technical_core_v2 import TechnicalBaselineForecast, TechnicalCoreState
from workspace_composer_v2 import CachedLayerOutput, WorkspaceSnapshotV2


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


def _sqlite_connect(tmp_path, monkeypatch):
    db_path = tmp_path / "pg-v2-test.db"

    @contextmanager
    def connect_for_test():
        from database import connect

        with connect(db_path, force_sqlite=True) as db:
            yield db

    monkeypatch.setattr(persistence, "connect", connect_for_test)

    with connect_for_test() as db:
        db.executescript(
            """
            CREATE TABLE pg_v2_forecast_layer_outputs (
                layer_output_id TEXT PRIMARY KEY,
                market_id INTEGER NOT NULL,
                as_of TEXT NOT NULL,
                layer_name TEXT NOT NULL,
                layer_version TEXT NOT NULL,
                input_fingerprint TEXT NOT NULL,
                directional_bias REAL,
                velocity_modifier REAL,
                uncertainty_modifier REAL,
                reversal_probability REAL,
                squeeze_probability REAL,
                regime_confidence REAL,
                details_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(market_id, as_of, layer_name, layer_version, input_fingerprint)
            );
            """
        )


def test_layer_output_round_trip_preserves_workspace_cache(tmp_path, monkeypatch):
    _sqlite_connect(tmp_path, monkeypatch)
    state = _state()
    baseline = _baseline(state)
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

    persistence.persist_layer_output(market_id=1, as_of=state.as_of, output=layer)
    restored = persistence.load_cached_layer_outputs(market_id=1, workspace=workspace)

    assert set(restored) == {"technical-interpreter"}
    loaded = restored["technical-interpreter"]
    assert loaded.directional_bias == 0.55
    assert loaded.confidence == 0.78
    assert loaded.details["human_summary"].startswith("Momentum")


def test_wrong_fingerprint_does_not_restore_cached_layers(tmp_path, monkeypatch):
    _sqlite_connect(tmp_path, monkeypatch)
    state = _state()
    baseline = _baseline(state)
    workspace = WorkspaceSnapshotV2(
        market=state.market,
        as_of=state.as_of,
        technical_state=state,
        technical_baselines={3600: baseline},
    )
    layer = CachedLayerOutput(
        layer_name="technical-interpreter",
        layer_version="technical-interpreter-v2.1",
        input_fingerprint="fingerprint-a",
        directional_bias=0.1,
        details={},
    )

    persistence.persist_layer_output(market_id=1, as_of=state.as_of, output=layer)
    restored = persistence.load_cached_layer_outputs(market_id=1, workspace=workspace)

    assert restored == {}


def test_persisted_details_keep_confidence_when_not_explicitly_present(tmp_path, monkeypatch):
    _sqlite_connect(tmp_path, monkeypatch)
    state = _state()
    baseline = _baseline(state)
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
        confidence=0.66,
        details={"human_summary": "Technical-only explanation."},
    )

    persistence.persist_layer_output(market_id=1, as_of=state.as_of, output=layer)

    with persistence.connect() as db:
        row = db.execute(
            "SELECT details_json FROM pg_v2_forecast_layer_outputs WHERE market_id = ?",
            (1,),
        ).fetchone()
    details = json.loads(row[0])
    assert details["confidence"] == 0.66
