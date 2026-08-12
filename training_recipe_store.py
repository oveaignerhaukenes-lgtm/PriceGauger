from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any

from database import connect
from forecast_contracts import FORECAST_HORIZONS_HOURS


DEFAULT_FORECAST_TRAINING_RECIPE = "forecast-training-v1-1m"
ACTIVE_FORECAST_TRAINING_RECIPE = "forecast-training-v2-multi-horizon-1m"


@dataclass(frozen=True, slots=True)
class TrainingRecipe:
    recipe_id: str
    sample_interval_seconds: int
    horizons_hours: tuple[float, ...]
    min_complete_samples: int
    recent_sample_limit: int
    movement_learning: bool
    direction_learning: bool
    regime_learning: bool
    description: str

    def to_record(self) -> dict[str, Any]:
        record = asdict(self)
        record["horizons_hours"] = list(self.horizons_hours)
        return record


DEFAULT_RECIPE = TrainingRecipe(
    recipe_id=DEFAULT_FORECAST_TRAINING_RECIPE,
    sample_interval_seconds=60,
    horizons_hours=(0.5, 1.0, 4.0, 12.0, 24.0),
    min_complete_samples=6,
    recent_sample_limit=40,
    movement_learning=True,
    direction_learning=False,
    regime_learning=False,
    description=(
        "First online self-calibration recipe. Learns movement magnitude from complete "
        "forecast outcomes per market and horizon. Direction and regime learning are "
        "explicitly deferred so later experiments remain attributable."
    ),
)

MULTI_HORIZON_RECIPE = TrainingRecipe(
    recipe_id=ACTIVE_FORECAST_TRAINING_RECIPE,
    sample_interval_seconds=60,
    horizons_hours=FORECAST_HORIZONS_HOURS,
    min_complete_samples=6,
    recent_sample_limit=40,
    movement_learning=True,
    direction_learning=False,
    regime_learning=False,
    description=(
        "Eight-horizon online calibration recipe for 5m, 15m, 30m, 1h, 4h, 12h, "
        "24h and 7d forecasts. Movement magnitude learns independently per market and "
        "horizon. Direction remains inherited from Decision State until a separately "
        "versioned horizon-direction model is validated."
    ),
)


class TrainingRecipeStore:
    """Append-only archive of the exact recipes used by adaptive forecast learning."""

    def __init__(self, path: str | Path = "pricegauger.db") -> None:
        self.path = str(path)
        with connect(self.path) as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS forecast_training_recipes (
                    recipe_id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
        self.ensure(DEFAULT_RECIPE)
        self.ensure(MULTI_HORIZON_RECIPE)

    def ensure(self, recipe: TrainingRecipe) -> None:
        payload = json.dumps(recipe.to_record(), ensure_ascii=False, sort_keys=True)
        with connect(self.path) as db:
            existing = db.execute(
                "SELECT payload_json FROM forecast_training_recipes WHERE recipe_id=?",
                (recipe.recipe_id,),
            ).fetchone()
            if existing is not None:
                if str(existing["payload_json"]) != payload:
                    raise ValueError(
                        f"training recipe {recipe.recipe_id} already exists with different contents; "
                        "create a new recipe_id instead of mutating archived training"
                    )
                return
            db.execute(
                "INSERT INTO forecast_training_recipes(recipe_id, payload_json) VALUES (?, ?)",
                (recipe.recipe_id, payload),
            )

    def load(self, recipe_id: str) -> TrainingRecipe | None:
        with connect(self.path) as db:
            row = db.execute(
                "SELECT payload_json FROM forecast_training_recipes WHERE recipe_id=?",
                (str(recipe_id),),
            ).fetchone()
        if row is None:
            return None
        record = json.loads(row["payload_json"])
        record["horizons_hours"] = tuple(float(item) for item in record.get("horizons_hours") or ())
        return TrainingRecipe(**record)

    def load_all(self) -> tuple[TrainingRecipe, ...]:
        with connect(self.path) as db:
            rows = db.execute(
                "SELECT payload_json FROM forecast_training_recipes ORDER BY recorded_at, recipe_id"
            ).fetchall()
        result: list[TrainingRecipe] = []
        for row in rows:
            record = json.loads(row["payload_json"])
            record["horizons_hours"] = tuple(float(item) for item in record.get("horizons_hours") or ())
            result.append(TrainingRecipe(**record))
        return tuple(result)
