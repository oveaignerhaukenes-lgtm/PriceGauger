from __future__ import annotations

import pytest

from recipe_registry_v2 import (
    TA_INTERPRETER_V1,
    TA_ONLY_V1,
    TECHNICAL_CORE_RECIPE_V2_1,
    AnalysisRecipeSpecV2,
    analysis_recipe_by_identity_v2,
)
from technical_interpreter_v2 import TECHNICAL_INTERPRETER_V2_RECIPE


def test_recipe_ids_are_stable_and_distinct():
    assert str(TA_ONLY_V1.recipe_id) == str(TA_ONLY_V1.recipe_id)
    assert str(TA_INTERPRETER_V1.recipe_id) == str(TA_INTERPRETER_V1.recipe_id)
    assert TA_ONLY_V1.recipe_id != TA_INTERPRETER_V1.recipe_id
    assert TECHNICAL_CORE_RECIPE_V2_1.recipe_id not in {
        TA_ONLY_V1.recipe_id,
        TA_INTERPRETER_V1.recipe_id,
    }


def test_ta_only_has_no_optional_layers():
    assert TA_ONLY_V1.name == "TA-only"
    assert TA_ONLY_V1.version == 1
    assert TA_ONLY_V1.enabled_layers == ()
    assert TA_ONLY_V1.layer_versions_dict() == {}


def test_ta_interpreter_pins_exact_layer_version():
    assert TA_INTERPRETER_V1.enabled_layers == ("technical_interpreter",)
    assert TA_INTERPRETER_V1.layer_versions_dict() == {
        "technical_interpreter": TECHNICAL_INTERPRETER_V2_RECIPE
    }


def test_recipe_lookup_requires_explicit_name_and_version():
    assert analysis_recipe_by_identity_v2("TA-only", 1) is TA_ONLY_V1
    with pytest.raises(KeyError):
        analysis_recipe_by_identity_v2("TA-only", 2)


def test_layer_version_contract_must_exactly_match_enabled_layers():
    invalid = AnalysisRecipeSpecV2(
        name="invalid",
        version=1,
        technical_recipe=TECHNICAL_CORE_RECIPE_V2_1,
        enabled_layers=("technical_interpreter",),
        layer_versions=(),
    )
    with pytest.raises(ValueError):
        invalid.layer_versions_dict()
