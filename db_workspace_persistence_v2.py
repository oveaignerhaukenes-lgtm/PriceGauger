from __future__ import annotations

import json
from typing import Any
from uuid import UUID, uuid4, uuid5

from database import connect
from technical_core_v2 import TechnicalBaselineForecast, TechnicalCoreState
from workspace_composer_v2 import CachedLayerOutput, WorkspaceSnapshotV2


PERSISTENCE_NAMESPACE_V2 = UUID("3a53f5bd-9420-41e1-a52b-b97417c47964")


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _json_placeholder(db) -> str:
    return "?::jsonb" if db.is_postgres else "?"


def technical_state_identity_v2(*, market_id: int, as_of: str, technical_recipe_id: UUID) -> UUID:
    return uuid5(
        PERSISTENCE_NAMESPACE_V2,
        f"technical-state:{int(market_id)}:{as_of}:{technical_recipe_id}",
    )


def forecast_identity_v2(
    *,
    market_id: int,
    as_of: str,
    horizon_seconds: int,
    technical_state_id: UUID,
    analysis_recipe_id: UUID,
) -> UUID:
    return uuid5(
        PERSISTENCE_NAMESPACE_V2,
        (
            f"forecast:{int(market_id)}:{as_of}:{int(horizon_seconds)}:"
            f"{technical_state_id}:{analysis_recipe_id}"
        ),
    )


def persist_technical_recipe(
    *,
    technical_recipe_id: UUID,
    name: str,
    version: int,
    parameters: dict[str, Any],
) -> None:
    with connect() as db:
        json_value = _json_placeholder(db)
        db.execute(
            f"""
            INSERT INTO pg_v2_technical_recipes
                (technical_recipe_id, name, version, parameters_json)
            VALUES (?, ?, ?, {json_value})
            ON CONFLICT (name, version) DO NOTHING
            """,
            (str(technical_recipe_id), name, int(version), _json(parameters)),
        )


def persist_technical_state(
    *,
    market_id: int,
    technical_recipe_id: UUID,
    state: TechnicalCoreState,
    technical_state_id: UUID | None = None,
) -> UUID:
    state_id = technical_state_id or technical_state_identity_v2(
        market_id=market_id,
        as_of=state.as_of,
        technical_recipe_id=technical_recipe_id,
    )
    features = {
        "primary_timeframe": state.primary_timeframe,
        "structure_state": state.structure_state,
        "score": state.score,
        "confidence": state.confidence,
        "snapshots": state.snapshots,
        "recipe_version": state.recipe_version,
    }
    with connect() as db:
        json_value = _json_placeholder(db)
        db.execute(
            f"""
            INSERT INTO pg_v2_technical_states
                (technical_state_id, market_id, as_of, technical_recipe_id,
                 trend_state, momentum_state, volatility_state, features_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, {json_value})
            ON CONFLICT (market_id, as_of, technical_recipe_id) DO NOTHING
            """,
            (
                str(state_id),
                int(market_id),
                state.as_of,
                str(technical_recipe_id),
                state.trend_state,
                state.momentum_state,
                state.volatility_state,
                _json(features),
            ),
        )
    return state_id


def persist_analysis_recipe(
    *,
    analysis_recipe_id: UUID,
    name: str,
    version: int,
    technical_recipe_id: UUID,
    enabled_layers: tuple[str, ...],
    layer_versions: dict[str, str],
) -> None:
    """Persist an immutable analysis recipe identity.

    A (name, version) pair is a historical contract. Changing enabled layers or
    layer versions therefore requires a new recipe version rather than rewriting
    an existing row that old forecasts already reference.
    """
    with connect() as db:
        json_value = _json_placeholder(db)
        db.execute(
            f"""
            INSERT INTO pg_v2_analysis_recipes
                (analysis_recipe_id, name, version, technical_recipe_id,
                 enabled_layers_json, layer_versions_json)
            VALUES (?, ?, ?, ?, {json_value}, {json_value})
            ON CONFLICT (name, version) DO NOTHING
            """,
            (
                str(analysis_recipe_id),
                name,
                int(version),
                str(technical_recipe_id),
                _json(list(enabled_layers)),
                _json(layer_versions),
            ),
        )


def persist_baseline_forecast(
    *,
    market_id: int,
    technical_state_id: UUID,
    analysis_recipe_id: UUID,
    baseline: TechnicalBaselineForecast,
    forecast_id: UUID | None = None,
) -> UUID:
    stored_forecast_id = forecast_id or forecast_identity_v2(
        market_id=market_id,
        as_of=baseline.as_of,
        horizon_seconds=baseline.horizon_seconds,
        technical_state_id=technical_state_id,
        analysis_recipe_id=analysis_recipe_id,
    )
    with connect() as db:
        json_value = _json_placeholder(db)
        db.execute(
            f"""
            INSERT INTO pg_v2_forecasts
                (forecast_id, market_id, as_of, horizon_seconds,
                 technical_state_id, analysis_recipe_id,
                 baseline_return, composed_return, lower_return, upper_return,
                 path_spec_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, {json_value})
            ON CONFLICT (forecast_id) DO NOTHING
            """,
            (
                str(stored_forecast_id),
                int(market_id),
                baseline.as_of,
                int(baseline.horizon_seconds),
                str(technical_state_id),
                str(analysis_recipe_id),
                baseline.expected_return,
                baseline.expected_return,
                baseline.lower_return,
                baseline.upper_return,
                _json({
                    "direction": baseline.direction,
                    "path_shape": baseline.path_shape,
                    "confidence": baseline.confidence,
                    "recipe_version": baseline.recipe_version,
                }),
            ),
        )
    return stored_forecast_id


def persist_layer_output(
    *,
    market_id: int,
    as_of: str,
    output: CachedLayerOutput,
    layer_output_id: UUID | None = None,
) -> UUID:
    stored_id = layer_output_id or uuid4()
    details = dict(output.details)
    details.setdefault("confidence", output.confidence)
    with connect() as db:
        json_value = _json_placeholder(db)
        db.execute(
            f"""
            INSERT INTO pg_v2_forecast_layer_outputs
                (layer_output_id, market_id, as_of, layer_name, layer_version,
                 input_fingerprint, directional_bias, velocity_modifier,
                 uncertainty_modifier, reversal_probability, squeeze_probability,
                 regime_confidence, details_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, {json_value})
            ON CONFLICT (market_id, as_of, layer_name, layer_version, input_fingerprint)
            DO UPDATE SET
                directional_bias = EXCLUDED.directional_bias,
                velocity_modifier = EXCLUDED.velocity_modifier,
                uncertainty_modifier = EXCLUDED.uncertainty_modifier,
                reversal_probability = EXCLUDED.reversal_probability,
                squeeze_probability = EXCLUDED.squeeze_probability,
                regime_confidence = EXCLUDED.regime_confidence,
                details_json = EXCLUDED.details_json
            """,
            (
                str(stored_id),
                int(market_id),
                as_of,
                output.layer_name,
                output.layer_version,
                output.input_fingerprint,
                output.directional_bias,
                output.velocity_modifier,
                output.uncertainty_modifier,
                output.reversal_probability,
                output.squeeze_probability,
                output.confidence,
                _json(details),
            ),
        )
    return stored_id


def load_cached_layer_outputs(
    *,
    market_id: int,
    workspace: WorkspaceSnapshotV2,
) -> dict[str, CachedLayerOutput]:
    with connect() as db:
        rows = db.execute(
            """
            SELECT layer_name, layer_version, input_fingerprint,
                   directional_bias, velocity_modifier, uncertainty_modifier,
                   reversal_probability, squeeze_probability, regime_confidence,
                   details_json
            FROM pg_v2_forecast_layer_outputs
            WHERE market_id = ? AND as_of = ? AND input_fingerprint = ?
            ORDER BY created_at ASC
            """,
            (int(market_id), workspace.as_of, workspace.fingerprint),
        ).fetchall()

    loaded: dict[str, CachedLayerOutput] = {}
    for row in rows:
        details_raw = row["details_json"] if isinstance(row, dict) else row[9]
        if isinstance(details_raw, str):
            details = json.loads(details_raw)
        else:
            details = dict(details_raw or {})
        name = row["layer_name"] if isinstance(row, dict) else row[0]
        loaded[name] = CachedLayerOutput(
            layer_name=name,
            layer_version=row["layer_version"] if isinstance(row, dict) else row[1],
            input_fingerprint=row["input_fingerprint"] if isinstance(row, dict) else row[2],
            directional_bias=float((row["directional_bias"] if isinstance(row, dict) else row[3]) or 0.0),
            velocity_modifier=float((row["velocity_modifier"] if isinstance(row, dict) else row[4]) or 0.0),
            uncertainty_modifier=float((row["uncertainty_modifier"] if isinstance(row, dict) else row[5]) or 0.0),
            reversal_probability=row["reversal_probability"] if isinstance(row, dict) else row[6],
            squeeze_probability=row["squeeze_probability"] if isinstance(row, dict) else row[7],
            confidence=row["regime_confidence"] if isinstance(row, dict) else row[8],
            details=details,
        )
    return loaded


def restore_workspace_layer_cache(
    *,
    market_id: int,
    workspace: WorkspaceSnapshotV2,
) -> WorkspaceSnapshotV2:
    for output in load_cached_layer_outputs(market_id=market_id, workspace=workspace).values():
        workspace.cache_layer(output)
    return workspace
