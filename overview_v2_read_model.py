from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Iterable, Mapping

from database import connect
from forecast_path_model_v2 import build_forecast_path_v2
from overview_chart_history import load_overview_chart_history
from realtime_market_data import RealtimeMarketDataStore
from recipe_registry_v2 import TA_INTERPRETER_V1, TA_ONLY_V1
from workspace_composer_v2 import AnalysisRecipeV2, compose_forecast
from workspace_loader_v2 import load_workspace_v2


@dataclass(frozen=True, slots=True)
class ForecastGhostV2:
    as_of: str
    horizon_seconds: int
    expected_return: float
    lower_return: float
    upper_return: float
    path_shape: str
    path_profile: tuple[tuple[float, float], ...] = ()


@dataclass(frozen=True, slots=True)
class OverviewTechnicalV2:
    market: str
    as_of: str
    horizon_seconds: int
    available_horizons: tuple[int, ...]
    direction: str
    baseline_return: float
    expected_return: float
    lower_return: float
    upper_return: float
    confidence: float
    path_shape: str
    trend_state: str
    momentum_state: str
    volatility_state: str
    structure_state: str
    technical_score: float
    recipe_label: str
    applied_layers: tuple[str, ...]
    interpreter_available: bool
    interpreter_summary: str | None
    interpreter_confidence: float | None
    path_profile: tuple[tuple[float, float], ...] = ()
    path_rationale: str = ""
    path_phases: tuple[str, ...] = ()
    path_source_timeframe: str | None = None
    expected_low_return: float | None = None
    expected_high_return: float | None = None
    price_history: tuple[tuple[str, float], ...] = ()
    feed_delay_minutes: float | None = None
    forecast_ghosts: tuple[ForecastGhostV2, ...] = ()


def _closest_horizon(available: Iterable[int], requested: int | None) -> int:
    values = sorted({int(value) for value in available if int(value) > 0})
    if not values:
        raise LookupError("workspace contains no forecast horizons")
    if requested is None:
        return values[0]
    return min(values, key=lambda value: (abs(value - int(requested)), value))


def _matching_interpreter(workspace):
    for key in ("technical-interpreter", "technical_interpreter"):
        output = workspace.layer_outputs.get(key)
        if output is not None and output.input_fingerprint == workspace.fingerprint:
            return key, output
    return None, None


def project_workspace_v2(
    workspace,
    *,
    requested_horizon_seconds: int | None = None,
    enable_interpreter: bool = False,
    price_history: Iterable[tuple[str, float]] = (),
    feed_delay_minutes: float | None = None,
    forecast_ghosts: Iterable[ForecastGhostV2] = (),
) -> OverviewTechnicalV2:
    """Project one coherent persisted workspace into a visualization read model."""
    horizon = _closest_horizon(workspace.technical_baselines, requested_horizon_seconds)
    layer_key, interpreter = _matching_interpreter(workspace)
    use_interpreter = bool(enable_interpreter and interpreter is not None and layer_key is not None)

    if use_interpreter:
        recipe_spec = TA_INTERPRETER_V1
        recipe = AnalysisRecipeV2(
            name=recipe_spec.name,
            version=recipe_spec.version,
            enabled_layers=(str(layer_key),),
        )
    else:
        recipe_spec = TA_ONLY_V1
        recipe = AnalysisRecipeV2(
            name=recipe_spec.name,
            version=recipe_spec.version,
            enabled_layers=(),
        )

    composed = compose_forecast(workspace, horizon_seconds=horizon, recipe=recipe)
    summary = None
    interpreter_confidence = None
    if interpreter is not None:
        raw_summary = interpreter.details.get("human_summary")
        summary = str(raw_summary).strip() if raw_summary else None
        interpreter_confidence = interpreter.confidence

    state = workspace.technical_state
    path = build_forecast_path_v2(
        state=state,
        horizon_seconds=horizon,
        direction=composed.direction,
        expected_return=float(composed.composed_return),
        lower_return=float(composed.lower_return),
        upper_return=float(composed.upper_return),
        path_shape=composed.path_shape,
    )
    return OverviewTechnicalV2(
        market=workspace.market,
        as_of=workspace.as_of,
        horizon_seconds=horizon,
        available_horizons=tuple(sorted(int(value) for value in workspace.technical_baselines)),
        direction=composed.direction,
        baseline_return=float(composed.baseline_return),
        expected_return=float(composed.composed_return),
        lower_return=float(composed.lower_return),
        upper_return=float(composed.upper_return),
        confidence=float(composed.technical_baseline.confidence),
        path_shape=composed.path_shape,
        trend_state=state.trend_state,
        momentum_state=state.momentum_state,
        volatility_state=state.volatility_state,
        structure_state=state.structure_state,
        technical_score=float(state.score),
        recipe_label=f"{recipe_spec.name} v{recipe_spec.version}",
        applied_layers=tuple(composed.applied_layers),
        interpreter_available=interpreter is not None,
        interpreter_summary=summary,
        interpreter_confidence=interpreter_confidence,
        path_profile=path.points,
        path_rationale=path.rationale,
        path_phases=path.phases,
        path_source_timeframe=path.source_timeframe,
        expected_low_return=path.expected_low_return,
        expected_high_return=path.expected_high_return,
        price_history=tuple(price_history),
        feed_delay_minutes=None if feed_delay_minutes is None else float(feed_delay_minutes),
        forecast_ghosts=tuple(forecast_ghosts),
    )


def _feed_delay_by_market(db_path: str) -> dict[str, float | None]:
    try:
        statuses = RealtimeMarketDataStore(db_path).load_statuses()
    except Exception:
        return {}
    return {
        status.market: (None if status.delay_minutes is None else float(status.delay_minutes))
        for status in statuses
    }


def _path_profile_from_spec(raw) -> tuple[tuple[float, float], ...]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            raw = {}
    if not isinstance(raw, dict):
        return ()
    points = raw.get("path_profile") or ()
    result: list[tuple[float, float]] = []
    for item in points:
        try:
            x, value = item
            result.append((float(x), float(value)))
        except (TypeError, ValueError):
            continue
    return tuple(result)


def _recent_forecast_ghosts(
    db_path: str,
    *,
    market_id: int,
    current_as_of: str,
    horizon_seconds: int,
    limit: int = 8,
) -> tuple[ForecastGhostV2, ...]:
    """Load prior immutable TA-only forecasts for visual forecast-vs-reality comparison."""
    with connect(db_path) as db:
        rows = db.execute(
            """
            SELECT as_of, horizon_seconds,
                   COALESCE(composed_return, baseline_return, 0.0) AS expected_return,
                   lower_return, upper_return, path_spec_json
            FROM pg_v2_forecasts
            WHERE market_id = ?
              AND horizon_seconds = ?
              AND analysis_recipe_id = ?
              AND as_of < ?
            ORDER BY as_of DESC
            LIMIT ?
            """,
            (
                int(market_id),
                int(horizon_seconds),
                str(TA_ONLY_V1.recipe_id),
                current_as_of,
                max(1, min(10, int(limit))),
            ),
        ).fetchall()

    result: list[ForecastGhostV2] = []
    for row in rows:
        get = (lambda key, index: row[key]) if isinstance(row, dict) else (lambda key, index: row[index])
        raw_spec = get("path_spec_json", 5)
        if isinstance(raw_spec, str):
            try:
                spec = json.loads(raw_spec)
            except (TypeError, ValueError, json.JSONDecodeError):
                spec = {}
        elif isinstance(raw_spec, dict):
            spec = raw_spec
        else:
            spec = {}
        expected = float(get("expected_return", 2) or 0.0)
        lower = get("lower_return", 3)
        upper = get("upper_return", 4)
        result.append(
            ForecastGhostV2(
                as_of=str(get("as_of", 0)),
                horizon_seconds=int(get("horizon_seconds", 1)),
                expected_return=expected,
                lower_return=expected if lower is None else float(lower),
                upper_return=expected if upper is None else float(upper),
                path_shape=str(spec.get("path_shape") or "DRIFT"),
                path_profile=_path_profile_from_spec(spec),
            )
        )
    return tuple(reversed(result))


def load_v2_overview_snapshots(
    *,
    requested_horizons: Mapping[str, int] | None = None,
    interpreter_by_market: Mapping[str, bool] | None = None,
    db_path: str = "pricegauger.db",
) -> dict[str, OverviewTechnicalV2]:
    """Load read-only persisted v2 workspaces and cheap cached compositions."""
    with connect(db_path) as db:
        rows = db.execute(
            "SELECT market_id, name FROM pg_v2_markets WHERE active = TRUE ORDER BY market_id"
        ).fetchall()

    result: dict[str, OverviewTechnicalV2] = {}
    requested_horizons = requested_horizons or {}
    interpreter_by_market = interpreter_by_market or {}
    delay_by_market = _feed_delay_by_market(db_path)
    for row in rows:
        market_id = int(row["market_id"] if isinstance(row, dict) else row[0])
        market = str(row["name"] if isinstance(row, dict) else row[1])
        try:
            workspace = load_workspace_v2(
                market_id=market_id,
                analysis_recipe_id=TA_ONLY_V1.recipe_id,
                restore_cached_layers=True,
            )
            requested = requested_horizons.get(market)
            horizon = _closest_horizon(workspace.technical_baselines, requested)
            history = load_overview_chart_history(
                db_path,
                market=market,
                as_of=workspace.as_of,
                horizon_hours=float(horizon) / 3600.0,
                technical_limit=360,
                recent_1m_limit=600,
            )
            ghosts = _recent_forecast_ghosts(
                db_path,
                market_id=market_id,
                current_as_of=workspace.as_of,
                horizon_seconds=horizon,
                limit=8,
            )
            result[market] = project_workspace_v2(
                workspace,
                requested_horizon_seconds=horizon,
                enable_interpreter=bool(interpreter_by_market.get(market, False)),
                price_history=history,
                feed_delay_minutes=delay_by_market.get(market),
                forecast_ghosts=ghosts,
            )
        except (KeyError, LookupError):
            continue
    return result
