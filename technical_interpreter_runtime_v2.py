from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from db_workspace_persistence_v2 import persist_layer_output
from technical_interpreter_v2 import (
    TECHNICAL_INTERPRETER_V2_RECIPE,
    TechnicalInterpretation,
    build_technical_interpreter_payload,
    validate_technical_interpretation,
)
from workspace_composer_v2 import (
    CachedLayerOutput,
    WorkspaceSnapshotV2,
    technical_interpretation_to_layer_output,
)


TechnicalInterpreterCallable = Callable[[dict[str, Any]], Mapping[str, Any]]


@dataclass(frozen=True, slots=True)
class TechnicalInterpreterRuntimeResultV2:
    output: CachedLayerOutput
    interpretation: TechnicalInterpretation | None
    source: str


def _matching_cached_output(
    workspace: WorkspaceSnapshotV2,
    *,
    recipe_version: str,
) -> CachedLayerOutput | None:
    cached = workspace.layer_outputs.get("technical-interpreter")
    if cached is None:
        return None
    if cached.input_fingerprint != workspace.fingerprint:
        return None
    if cached.layer_version != recipe_version:
        return None
    return cached


def run_technical_interpreter_v2(
    *,
    workspace: WorkspaceSnapshotV2,
    interpreter: TechnicalInterpreterCallable,
    recipe_version: str = TECHNICAL_INTERPRETER_V2_RECIPE,
    market_id: int | None = None,
    persist: bool = False,
    allow_cached: bool = True,
) -> TechnicalInterpreterRuntimeResultV2:
    """Run the optional, technical-only interpreter for one workspace snapshot.

    The callable receives only the normalized Technical Core payload. It has no
    access here to news, macro, regime, Telegram, positions or execution state.
    Returned data must pass the existing strict TechnicalInterpretation contract
    before it can modify a forecast.
    """
    if persist and market_id is None:
        raise ValueError("market_id is required when persisting interpreter output")

    if allow_cached:
        cached = _matching_cached_output(workspace, recipe_version=recipe_version)
        if cached is not None:
            return TechnicalInterpreterRuntimeResultV2(
                output=cached,
                interpretation=None,
                source="cache",
            )

    payload = build_technical_interpreter_payload(workspace.technical_state)
    raw = interpreter(payload)
    if not isinstance(raw, Mapping):
        raise ValueError("technical interpreter must return an object")

    interpretation = validate_technical_interpretation(
        workspace.technical_state,
        dict(raw),
        recipe_version=recipe_version,
    )
    output = technical_interpretation_to_layer_output(workspace, interpretation)
    workspace.cache_layer(output)

    if persist:
        persist_layer_output(
            market_id=int(market_id),
            as_of=workspace.as_of,
            output=output,
        )

    return TechnicalInterpreterRuntimeResultV2(
        output=output,
        interpretation=interpretation,
        source="generated",
    )
