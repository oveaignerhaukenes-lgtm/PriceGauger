from __future__ import annotations

from dataclasses import asdict, dataclass, field
from hashlib import sha256
import json
from typing import Any, Iterable

from technical_core_v2 import TechnicalBaselineForecast, TechnicalCoreState
from technical_interpreter_v2 import TechnicalInterpretation


@dataclass(frozen=True, slots=True)
class AnalysisRecipeV2:
    name: str
    version: int
    enabled_layers: tuple[str, ...] = ()

    @property
    def identity(self) -> str:
        layers = "+".join(self.enabled_layers) if self.enabled_layers else "technical-only"
        return f"{self.name}:v{self.version}:{layers}"


@dataclass(frozen=True, slots=True)
class CachedLayerOutput:
    layer_name: str
    layer_version: str
    input_fingerprint: str
    directional_bias: float = 0.0
    velocity_modifier: float = 0.0
    uncertainty_modifier: float = 0.0
    reversal_probability: float | None = None
    squeeze_probability: float | None = None
    confidence: float | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ComposedForecastV2:
    market: str
    as_of: str
    horizon_seconds: int
    recipe_identity: str
    baseline_return: float
    composed_return: float
    lower_return: float
    upper_return: float
    direction: str
    path_shape: str
    applied_layers: tuple[str, ...]
    technical_baseline: TechnicalBaselineForecast

    def to_record(self) -> dict[str, Any]:
        record = asdict(self)
        record["technical_baseline"] = self.technical_baseline.to_record()
        return record


@dataclass(slots=True)
class WorkspaceSnapshotV2:
    market: str
    as_of: str
    technical_state: TechnicalCoreState
    technical_baselines: dict[int, TechnicalBaselineForecast]
    layer_outputs: dict[str, CachedLayerOutput] = field(default_factory=dict)

    @property
    def fingerprint(self) -> str:
        payload = {
            "market": self.market,
            "as_of": self.as_of,
            "technical_recipe": self.technical_state.recipe_version,
            "technical_score": self.technical_state.score,
            "technical_confidence": self.technical_state.confidence,
            "horizons": sorted(self.technical_baselines),
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return sha256(encoded).hexdigest()

    def cache_layer(self, output: CachedLayerOutput) -> None:
        if output.input_fingerprint != self.fingerprint:
            raise ValueError("layer output belongs to a different workspace snapshot")
        self.layer_outputs[output.layer_name] = output


def technical_interpretation_to_layer_output(
    workspace: WorkspaceSnapshotV2,
    interpretation: TechnicalInterpretation,
) -> CachedLayerOutput:
    if interpretation.market != workspace.market or interpretation.as_of != workspace.as_of:
        raise ValueError("technical interpretation does not match workspace snapshot")

    directional_bias = {
        "BULLISH": 1.0,
        "BEARISH": -1.0,
        "NEUTRAL": 0.0,
    }[interpretation.directional_bias]

    continuation_edge = interpretation.continuation_probability - interpretation.mean_reversion_probability
    breakout_edge = interpretation.breakout_probability - interpretation.rejection_probability
    velocity_modifier = 0.5 * continuation_edge + 0.5 * breakout_edge
    uncertainty_modifier = (0.5 - interpretation.confidence) * 0.6

    return CachedLayerOutput(
        layer_name="technical-interpreter",
        layer_version=interpretation.recipe_version,
        input_fingerprint=workspace.fingerprint,
        directional_bias=directional_bias * interpretation.confidence,
        velocity_modifier=max(-1.0, min(1.0, velocity_modifier)),
        uncertainty_modifier=max(-0.5, min(0.5, uncertainty_modifier)),
        reversal_probability=interpretation.mean_reversion_probability,
        squeeze_probability=interpretation.squeeze_probability,
        confidence=interpretation.confidence,
        details={
            "emphasis": interpretation.emphasis,
            "human_summary": interpretation.human_summary,
            "breakout_probability": interpretation.breakout_probability,
            "rejection_probability": interpretation.rejection_probability,
        },
    )


def compose_forecast(
    workspace: WorkspaceSnapshotV2,
    *,
    horizon_seconds: int,
    recipe: AnalysisRecipeV2,
) -> ComposedForecastV2:
    baseline = workspace.technical_baselines.get(int(horizon_seconds))
    if baseline is None:
        raise KeyError(f"workspace has no technical baseline for {horizon_seconds}s")

    expected = baseline.expected_return
    lower = baseline.lower_return
    upper = baseline.upper_return
    baseline_width = max(0.0, upper - lower)
    applied: list[str] = []

    for layer_name in recipe.enabled_layers:
        output = workspace.layer_outputs.get(layer_name)
        if output is None:
            raise KeyError(f"enabled layer is not cached: {layer_name}")
        if output.input_fingerprint != workspace.fingerprint:
            raise ValueError(f"cached layer is stale: {layer_name}")

        magnitude = max(abs(expected), baseline_width / 2.0, 0.0005)
        directional_shift = output.directional_bias * magnitude * 0.35
        velocity_shift = output.velocity_modifier * magnitude * 0.20
        expected += directional_shift + velocity_shift

        width_factor = max(0.45, 1.0 + output.uncertainty_modifier)
        half_width = (baseline_width / 2.0) * width_factor
        lower = expected - half_width
        upper = expected + half_width
        applied.append(layer_name)

    direction = "BULLISH" if expected > 0 else "BEARISH" if expected < 0 else "NEUTRAL"
    return ComposedForecastV2(
        market=workspace.market,
        as_of=workspace.as_of,
        horizon_seconds=int(horizon_seconds),
        recipe_identity=recipe.identity,
        baseline_return=baseline.expected_return,
        composed_return=round(expected, 8),
        lower_return=round(lower, 8),
        upper_return=round(upper, 8),
        direction=direction,
        path_shape=baseline.path_shape,
        applied_layers=tuple(applied),
        technical_baseline=baseline,
    )


def compose_many(
    workspace: WorkspaceSnapshotV2,
    *,
    horizon_seconds: int,
    recipes: Iterable[AnalysisRecipeV2],
) -> dict[str, ComposedForecastV2]:
    return {
        recipe.identity: compose_forecast(workspace, horizon_seconds=horizon_seconds, recipe=recipe)
        for recipe in recipes
    }
