from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from database import connect
from overview_chart_history import load_overview_chart_history
from recipe_registry_v2 import TA_INTERPRETER_V1, TA_ONLY_V1
from workspace_composer_v2 import AnalysisRecipeV2, compose_forecast
from workspace_loader_v2 import load_workspace_v2


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
    price_history: tuple[tuple[str, float], ...] = ()


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
) -> OverviewTechnicalV2:
    """Project one coherent persisted workspace into a visualization read model.

    Layer switching is deliberately composition-only. The function never invokes
    Technical Core, an interpreter/LLM, Saxo, or persistence. A Technical
    Interpreter refinement is available only when a fingerprint-matching cached
    output already exists on the workspace.
    """
    horizon = _closest_horizon(workspace.technical_baselines, requested_horizon_seconds)
    layer_key, interpreter = _matching_interpreter(workspace)
    use_interpreter = bool(enable_interpreter and interpreter is not None and layer_key is not None)

    if use_interpreter:
        recipe_spec = TA_INTERPRETER_V1
        # Runtime v2 historically persisted the canonical layer with a hyphen,
        # while the recipe registry uses an underscore. Resolve that read-only
        # storage alias here without mutating either historical contract.
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
        price_history=tuple(price_history),
    )


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
            result[market] = project_workspace_v2(
                workspace,
                requested_horizon_seconds=horizon,
                enable_interpreter=bool(interpreter_by_market.get(market, False)),
                price_history=history,
            )
        except (KeyError, LookupError):
            continue
    return result
