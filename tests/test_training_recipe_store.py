from __future__ import annotations

import pytest

from training_recipe_store import DEFAULT_RECIPE, TrainingRecipe, TrainingRecipeStore


def test_default_training_recipe_is_archived(tmp_path):
    store = TrainingRecipeStore(tmp_path / "recipes.sqlite3")
    loaded = store.load(DEFAULT_RECIPE.recipe_id)

    assert loaded == DEFAULT_RECIPE
    assert loaded.sample_interval_seconds == 60
    assert loaded.horizons_hours == (0.5, 1.0, 4.0, 12.0, 24.0)
    assert loaded.movement_learning is True
    assert loaded.direction_learning is False


def test_archived_recipe_cannot_be_mutated_under_same_id(tmp_path):
    store = TrainingRecipeStore(tmp_path / "recipes.sqlite3")
    changed = TrainingRecipe(
        recipe_id=DEFAULT_RECIPE.recipe_id,
        sample_interval_seconds=10,
        horizons_hours=DEFAULT_RECIPE.horizons_hours,
        min_complete_samples=DEFAULT_RECIPE.min_complete_samples,
        recent_sample_limit=DEFAULT_RECIPE.recent_sample_limit,
        movement_learning=True,
        direction_learning=True,
        regime_learning=False,
        description="different experiment",
    )

    with pytest.raises(ValueError, match="create a new recipe_id"):
        store.ensure(changed)
