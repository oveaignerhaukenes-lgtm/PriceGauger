from __future__ import annotations

import json
from typing import Any

from database import connect
from db_workspace_persistence_v2 import restore_workspace_layer_cache
from technical_core_v2 import TechnicalBaselineForecast, TechnicalCoreState
from workspace_composer_v2 import WorkspaceSnapshotV2


def _row_value(row, key: str, index: int):
    if isinstance(row, dict):
        return row[key]
    try:
        return row[key]
    except (TypeError, IndexError):
        return row[index]


def _json_value(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, str):
        return json.loads(value)
    return dict(value)


def _technical_state_from_row(row, *, market: str) -> TechnicalCoreState:
    features = _json_value(_row_value(row, "features_json", 7))
    return TechnicalCoreState(
        market=market,
        as_of=str(_row_value(row, "as_of", 1)),
        recipe_version=str(features.get("recipe_version") or _row_value(row, "recipe_name", 8)),
        primary_timeframe=str(features.get("primary_timeframe") or "30m"),
        trend_state=str(_row_value(row, "trend_state", 4) or "UNDETERMINED"),
        momentum_state=str(_row_value(row, "momentum_state", 5) or "UNDETERMINED"),
        volatility_state=str(_row_value(row, "volatility_state", 6) or "UNDETERMINED"),
        structure_state=str(features.get("structure_state") or "UNDETERMINED"),
        score=float(features.get("score") or 0.0),
        confidence=float(features.get("confidence") or 0.0),
        snapshots=dict(features.get("snapshots") or {}),
    )


def _baseline_from_row(row, *, state: TechnicalCoreState) -> TechnicalBaselineForecast:
    path_spec = _json_value(_row_value(row, "path_spec_json", 6))
    return TechnicalBaselineForecast(
        market=state.market,
        as_of=state.as_of,
        horizon_seconds=int(_row_value(row, "horizon_seconds", 0)),
        recipe_version=str(path_spec.get("recipe_version") or state.recipe_version),
        direction=str(path_spec.get("direction") or "NEUTRAL"),
        expected_return=float(_row_value(row, "baseline_return", 1) or 0.0),
        lower_return=float(_row_value(row, "lower_return", 3) or 0.0),
        upper_return=float(_row_value(row, "upper_return", 4) or 0.0),
        confidence=float(path_spec.get("confidence") or state.confidence),
        path_shape=str(path_spec.get("path_shape") or "DRIFT"),
        technical_state=state,
    )


def load_workspace_v2(
    *,
    market_id: int,
    analysis_recipe_id,
    as_of: str | None = None,
    restore_cached_layers: bool = True,
) -> WorkspaceSnapshotV2:
    """Reconstruct one coherent v2 workspace from persisted technical data.

    The selected Technical Core state is authoritative. Baselines are loaded only
    when they point to that exact technical_state_id and analysis recipe, so a
    workspace cannot silently mix forecasts from different observations.
    """
    with connect() as db:
        market_row = db.execute(
            "SELECT name FROM pg_v2_markets WHERE market_id = ?",
            (int(market_id),),
        ).fetchone()
        if market_row is None:
            raise KeyError(f"unknown v2 market_id: {market_id}")
        market = str(_row_value(market_row, "name", 0))

        where_as_of = "AND s.as_of <= ?" if as_of is not None else ""
        parameters: tuple[Any, ...] = (int(market_id),) if as_of is None else (int(market_id), as_of)
        state_row = db.execute(
            f"""
            SELECT s.technical_state_id, s.as_of, s.technical_recipe_id,
                   s.market_id, s.trend_state, s.momentum_state,
                   s.volatility_state, s.features_json, r.name AS recipe_name
            FROM pg_v2_technical_states s
            JOIN pg_v2_technical_recipes r
              ON r.technical_recipe_id = s.technical_recipe_id
            WHERE s.market_id = ? {where_as_of}
            ORDER BY s.as_of DESC, s.created_at DESC
            LIMIT 1
            """,
            parameters,
        ).fetchone()
        if state_row is None:
            raise LookupError(f"no persisted Technical Core state for {market}")

        state = _technical_state_from_row(state_row, market=market)
        technical_state_id = _row_value(state_row, "technical_state_id", 0)
        forecast_rows = db.execute(
            """
            SELECT horizon_seconds, baseline_return, composed_return,
                   lower_return, upper_return, as_of, path_spec_json
            FROM pg_v2_forecasts
            WHERE market_id = ?
              AND technical_state_id = ?
              AND analysis_recipe_id = ?
              AND as_of = ?
            ORDER BY horizon_seconds ASC, created_at DESC
            """,
            (int(market_id), str(technical_state_id), str(analysis_recipe_id), state.as_of),
        ).fetchall()

    baselines: dict[int, TechnicalBaselineForecast] = {}
    for row in forecast_rows:
        baseline = _baseline_from_row(row, state=state)
        baselines.setdefault(baseline.horizon_seconds, baseline)
    if not baselines:
        raise LookupError(
            f"no persisted technical baselines for {market} at {state.as_of} and requested analysis recipe"
        )

    workspace = WorkspaceSnapshotV2(
        market=market,
        as_of=state.as_of,
        technical_state=state,
        technical_baselines=baselines,
    )
    if restore_cached_layers:
        restore_workspace_layer_cache(market_id=int(market_id), workspace=workspace)
    return workspace
