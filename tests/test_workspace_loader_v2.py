from __future__ import annotations

import json
from contextlib import contextmanager
from uuid import uuid4

import workspace_loader_v2 as loader


def _sqlite_connect(tmp_path, monkeypatch):
    db_path = tmp_path / "workspace-loader-v2.db"

    @contextmanager
    def connect_for_test():
        from database import connect

        with connect(db_path, force_sqlite=True) as db:
            yield db

    monkeypatch.setattr(loader, "connect", connect_for_test)

    # restore_workspace_layer_cache resolves connect in its own module.
    import db_workspace_persistence_v2 as persistence

    monkeypatch.setattr(persistence, "connect", connect_for_test)

    with connect_for_test() as db:
        db.executescript(
            """
            CREATE TABLE pg_v2_markets (
                market_id INTEGER PRIMARY KEY,
                name TEXT NOT NULL UNIQUE
            );
            CREATE TABLE pg_v2_technical_recipes (
                technical_recipe_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                version INTEGER NOT NULL,
                parameters_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE pg_v2_technical_states (
                technical_state_id TEXT PRIMARY KEY,
                market_id INTEGER NOT NULL,
                as_of TEXT NOT NULL,
                technical_recipe_id TEXT NOT NULL,
                trend_state TEXT,
                momentum_state TEXT,
                volatility_state TEXT,
                features_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE pg_v2_forecasts (
                forecast_id TEXT PRIMARY KEY,
                market_id INTEGER NOT NULL,
                as_of TEXT NOT NULL,
                horizon_seconds INTEGER NOT NULL,
                technical_state_id TEXT NOT NULL,
                analysis_recipe_id TEXT NOT NULL,
                baseline_return REAL,
                composed_return REAL,
                lower_return REAL,
                upper_return REAL,
                path_spec_json TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
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
    return connect_for_test


def _seed(connect_for_test):
    recipe_id = str(uuid4())
    state_id = str(uuid4())
    analysis_recipe_id = str(uuid4())
    as_of = "2026-08-14T06:00:00+00:00"
    features = {
        "recipe_version": "technical-core-v2.1",
        "primary_timeframe": "30m",
        "structure_state": "HH_HL",
        "score": 0.42,
        "confidence": 0.71,
        "snapshots": {"30m": {"rsi_14": 63.0}},
    }
    path_spec = {
        "direction": "BULLISH",
        "path_shape": "DRIFT",
        "confidence": 0.71,
        "recipe_version": "technical-core-v2.1",
    }
    with connect_for_test() as db:
        db.execute("INSERT INTO pg_v2_markets (market_id, name) VALUES (?, ?)", (1, "Silver"))
        db.execute(
            "INSERT INTO pg_v2_technical_recipes (technical_recipe_id, name, version, parameters_json) VALUES (?, ?, ?, ?)",
            (recipe_id, "technical-core-v2.1", 1, "{}"),
        )
        db.execute(
            """
            INSERT INTO pg_v2_technical_states
                (technical_state_id, market_id, as_of, technical_recipe_id,
                 trend_state, momentum_state, volatility_state, features_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (state_id, 1, as_of, recipe_id, "BULLISH", "BULLISH", "NORMAL", json.dumps(features)),
        )
        for horizon, expected, lower, upper in (
            (300, 0.001, -0.002, 0.004),
            (3600, 0.004, -0.003, 0.011),
        ):
            db.execute(
                """
                INSERT INTO pg_v2_forecasts
                    (forecast_id, market_id, as_of, horizon_seconds,
                     technical_state_id, analysis_recipe_id, baseline_return,
                     composed_return, lower_return, upper_return, path_spec_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid4()), 1, as_of, horizon, state_id, analysis_recipe_id,
                    expected, expected, lower, upper, json.dumps(path_spec),
                ),
            )
    return analysis_recipe_id, state_id, as_of


def test_loader_reconstructs_coherent_workspace(tmp_path, monkeypatch):
    connect_for_test = _sqlite_connect(tmp_path, monkeypatch)
    analysis_recipe_id, _, as_of = _seed(connect_for_test)

    workspace = loader.load_workspace_v2(
        market_id=1,
        analysis_recipe_id=analysis_recipe_id,
        restore_cached_layers=False,
    )

    assert workspace.market == "Silver"
    assert workspace.as_of == as_of
    assert workspace.technical_state.score == 0.42
    assert workspace.technical_state.structure_state == "HH_HL"
    assert set(workspace.technical_baselines) == {300, 3600}
    assert all(item.technical_state == workspace.technical_state for item in workspace.technical_baselines.values())


def test_loader_does_not_mix_forecasts_from_other_state(tmp_path, monkeypatch):
    connect_for_test = _sqlite_connect(tmp_path, monkeypatch)
    analysis_recipe_id, _, _ = _seed(connect_for_test)
    newer_state_id = str(uuid4())
    with connect_for_test() as db:
        recipe_id = db.execute("SELECT technical_recipe_id FROM pg_v2_technical_recipes LIMIT 1").fetchone()[0]
        features = json.dumps({
            "recipe_version": "technical-core-v2.1",
            "primary_timeframe": "30m",
            "structure_state": "MIXED",
            "score": 0.1,
            "confidence": 0.4,
            "snapshots": {},
        })
        db.execute(
            """
            INSERT INTO pg_v2_technical_states
                (technical_state_id, market_id, as_of, technical_recipe_id,
                 trend_state, momentum_state, volatility_state, features_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (newer_state_id, 1, "2026-08-14T06:01:00+00:00", recipe_id, "NEUTRAL", "NEUTRAL", "NORMAL", features),
        )

    try:
        loader.load_workspace_v2(
            market_id=1,
            analysis_recipe_id=analysis_recipe_id,
            restore_cached_layers=False,
        )
    except LookupError as exc:
        assert "no persisted technical baselines" in str(exc)
    else:
        raise AssertionError("loader mixed older forecasts into a newer technical state")


def test_loader_restores_only_matching_fingerprint_cache(tmp_path, monkeypatch):
    connect_for_test = _sqlite_connect(tmp_path, monkeypatch)
    analysis_recipe_id, _, as_of = _seed(connect_for_test)
    workspace = loader.load_workspace_v2(
        market_id=1,
        analysis_recipe_id=analysis_recipe_id,
        restore_cached_layers=False,
    )

    with connect_for_test() as db:
        db.execute(
            """
            INSERT INTO pg_v2_forecast_layer_outputs
                (layer_output_id, market_id, as_of, layer_name, layer_version,
                 input_fingerprint, directional_bias, velocity_modifier,
                 uncertainty_modifier, regime_confidence, details_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid4()), 1, as_of, "technical-interpreter",
                "technical-interpreter-v2.1", workspace.fingerprint,
                0.5, 0.2, -0.1, 0.8, json.dumps({"human_summary": "Aligned technical evidence."}),
            ),
        )
        db.execute(
            """
            INSERT INTO pg_v2_forecast_layer_outputs
                (layer_output_id, market_id, as_of, layer_name, layer_version,
                 input_fingerprint, directional_bias, details_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid4()), 1, as_of, "stale-layer", "v1",
                "wrong-fingerprint", -1.0, "{}",
            ),
        )

    restored = loader.load_workspace_v2(
        market_id=1,
        analysis_recipe_id=analysis_recipe_id,
        restore_cached_layers=True,
    )

    assert set(restored.layer_outputs) == {"technical-interpreter"}
    assert restored.layer_outputs["technical-interpreter"].confidence == 0.8
