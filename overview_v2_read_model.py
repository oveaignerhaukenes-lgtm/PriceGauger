from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from database import connect
from recipe_registry_v2 import TA_ONLY_V1
from workspace_loader_v2 import load_workspace_v2


@dataclass(frozen=True, slots=True)
class OverviewTechnicalV2:
    market: str
    as_of: str
    horizon_seconds: int
    direction: str
    expected_return: float
    lower_return: float
    upper_return: float
    confidence: float
    path_shape: str
    trend_state: str
    momentum_state: str
    structure_state: str
    interpreter_summary: str | None
    interpreter_confidence: float | None


def _closest_horizon(available: Iterable[int], requested: int | None) -> int:
    values = sorted({int(value) for value in available if int(value) > 0})
    if not values:
        raise LookupError("workspace contains no forecast horizons")
    if requested is None:
        return values[0]
    return min(values, key=lambda value: (abs(value - int(requested)), value))


def project_workspace_v2(workspace, *, requested_horizon_seconds: int | None = None) -> OverviewTechnicalV2:
    horizon = _closest_horizon(workspace.technical_baselines, requested_horizon_seconds)
    baseline = workspace.technical_baselines[horizon]
    interpreter = workspace.layer_outputs.get("technical-interpreter")
    if interpreter is None:
        # Early contract versions used an underscore. Accept it for read-only
        # compatibility without changing the canonical layer identity.
        interpreter = workspace.layer_outputs.get("technical_interpreter")

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
        direction=baseline.direction,
        expected_return=baseline.expected_return,
        lower_return=baseline.lower_return,
        upper_return=baseline.upper_return,
        confidence=baseline.confidence,
        path_shape=baseline.path_shape,
        trend_state=state.trend_state,
        momentum_state=state.momentum_state,
        structure_state=state.structure_state,
        interpreter_summary=summary,
        interpreter_confidence=interpreter_confidence,
    )


def load_v2_overview_snapshots(
    *,
    requested_horizons: dict[str, int] | None = None,
) -> dict[str, OverviewTechnicalV2]:
    """Load best-effort read-only v2 projections for active markets.

    Missing/uninitialized v2 data is intentionally skipped. Overview remains
    operational on the existing production read path until a later explicit
    runtime cutover capability.
    """
    with connect() as db:
        rows = db.execute(
            "SELECT market_id, name FROM pg_v2_markets WHERE active = TRUE ORDER BY market_id"
        ).fetchall()

    result: dict[str, OverviewTechnicalV2] = {}
    for row in rows:
        market_id = int(row["market_id"] if isinstance(row, dict) else row[0])
        market = str(row["name"] if isinstance(row, dict) else row[1])
        try:
            workspace = load_workspace_v2(
                market_id=market_id,
                analysis_recipe_id=TA_ONLY_V1.recipe_id,
                restore_cached_layers=True,
            )
            requested = None if requested_horizons is None else requested_horizons.get(market)
            result[market] = project_workspace_v2(
                workspace,
                requested_horizon_seconds=requested,
            )
        except (KeyError, LookupError):
            continue
    return result
