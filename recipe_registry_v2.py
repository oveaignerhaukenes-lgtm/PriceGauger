from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid5

from technical_core_v2 import TECHNICAL_CORE_V2_RECIPE
from technical_interpreter_v2 import TECHNICAL_INTERPRETER_V2_RECIPE


RECIPE_NAMESPACE_V2 = UUID("f69ee976-b63b-4f61-8f50-7508b99fbff7")


def _stable_id(kind: str, name: str, version: int) -> UUID:
    if version <= 0:
        raise ValueError("recipe version must be positive")
    return uuid5(RECIPE_NAMESPACE_V2, f"{kind}:{name}:v{version}")


@dataclass(frozen=True, slots=True)
class TechnicalRecipeSpecV2:
    name: str
    version: int
    parameters: tuple[tuple[str, str], ...]

    @property
    def recipe_id(self) -> UUID:
        return _stable_id("technical", self.name, self.version)

    def parameters_dict(self) -> dict[str, str]:
        return dict(self.parameters)


@dataclass(frozen=True, slots=True)
class AnalysisRecipeSpecV2:
    name: str
    version: int
    technical_recipe: TechnicalRecipeSpecV2
    enabled_layers: tuple[str, ...] = ()
    layer_versions: tuple[tuple[str, str], ...] = ()

    @property
    def recipe_id(self) -> UUID:
        return _stable_id("analysis", self.name, self.version)

    def layer_versions_dict(self) -> dict[str, str]:
        versions = dict(self.layer_versions)
        if tuple(versions) != self.enabled_layers:
            raise ValueError("layer_versions must exactly match enabled_layers and preserve order")
        return versions


TECHNICAL_CORE_RECIPE_V2_1 = TechnicalRecipeSpecV2(
    name=TECHNICAL_CORE_V2_RECIPE,
    version=1,
    parameters=(("runtime", "canonical-1m-resample-v2.1"),),
)

TA_ONLY_V1 = AnalysisRecipeSpecV2(
    name="TA-only",
    version=1,
    technical_recipe=TECHNICAL_CORE_RECIPE_V2_1,
)

TA_INTERPRETER_V1 = AnalysisRecipeSpecV2(
    name="TA+Interpreter",
    version=1,
    technical_recipe=TECHNICAL_CORE_RECIPE_V2_1,
    enabled_layers=("technical_interpreter",),
    layer_versions=(("technical_interpreter", TECHNICAL_INTERPRETER_V2_RECIPE),),
)


ANALYSIS_RECIPES_V2: tuple[AnalysisRecipeSpecV2, ...] = (
    TA_ONLY_V1,
    TA_INTERPRETER_V1,
)


def analysis_recipe_by_identity_v2(name: str, version: int) -> AnalysisRecipeSpecV2:
    for recipe in ANALYSIS_RECIPES_V2:
        if recipe.name == name and recipe.version == int(version):
            return recipe
    raise KeyError(f"unknown v2 analysis recipe: {name} v{version}")
