from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from database import connect


ENGINE_NEWS_CONTEXT = "news_context"
ENGINE_HISTORICAL = "historical"
ENGINE_TECHNICAL = "technical"
ANALYSIS_ENGINES = (ENGINE_NEWS_CONTEXT, ENGINE_HISTORICAL, ENGINE_TECHNICAL)
DEFAULT_RESOLUTION = "AUTO"


@dataclass(frozen=True, slots=True)
class AnalysisViewPreferences:
    market: str
    enabled_engines: tuple[str, ...] = ANALYSIS_ENGINES
    resolution: str = DEFAULT_RESOLUTION
    show_learning: bool = True

    def __post_init__(self) -> None:
        market = str(self.market).strip()
        if not market:
            raise ValueError("market is required")
        object.__setattr__(self, "market", market)
        engines = tuple(engine for engine in ANALYSIS_ENGINES if engine in set(self.enabled_engines))
        object.__setattr__(self, "enabled_engines", engines)
        object.__setattr__(self, "resolution", str(self.resolution or DEFAULT_RESOLUTION))
        object.__setattr__(self, "show_learning", bool(self.show_learning))

    def enabled(self, engine: str) -> bool:
        return str(engine) in self.enabled_engines


class AnalysisViewPreferenceStore:
    """Persist market-detail view state independently of Streamlit sessions."""

    def __init__(self, path: str | Path = "pricegauger.db") -> None:
        self.path = str(path)
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS analysis_view_preferences (
                    market TEXT PRIMARY KEY,
                    enabled_engines_json TEXT NOT NULL,
                    resolution TEXT NOT NULL,
                    show_learning INTEGER NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

    def _connect(self):
        return connect(self.path)

    def load(self, market: str) -> AnalysisViewPreferences:
        market_name = str(market).strip()
        with self._connect() as db:
            row = db.execute(
                """
                SELECT enabled_engines_json, resolution, show_learning
                FROM analysis_view_preferences
                WHERE market=?
                """,
                (market_name,),
            ).fetchone()
        if row is None:
            return AnalysisViewPreferences(market=market_name)
        try:
            engines = tuple(json.loads(row["enabled_engines_json"]))
        except (TypeError, ValueError, json.JSONDecodeError):
            engines = ANALYSIS_ENGINES
        return AnalysisViewPreferences(
            market=market_name,
            enabled_engines=engines,
            resolution=str(row["resolution"] or DEFAULT_RESOLUTION),
            show_learning=bool(row["show_learning"]),
        )

    def save(self, preferences: AnalysisViewPreferences) -> None:
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO analysis_view_preferences(
                    market, enabled_engines_json, resolution, show_learning
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(market) DO UPDATE SET
                    enabled_engines_json=excluded.enabled_engines_json,
                    resolution=excluded.resolution,
                    show_learning=excluded.show_learning,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (
                    preferences.market,
                    json.dumps(list(preferences.enabled_engines), sort_keys=True),
                    preferences.resolution,
                    int(preferences.show_learning),
                ),
            )
