from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Iterable

from asset_state_mapping import AssetRecommendation
from market_interpretation import MarketInterpretation
from market_state import MarketState


class MarketStateStore:
    def __init__(self, path: str | Path = "pricegauger.db") -> None:
        self.path = str(path)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_schema(self) -> None:
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS market_interpretations (
                    event_id TEXT PRIMARY KEY,
                    cluster_id TEXT NOT NULL,
                    published_at TEXT NOT NULL,
                    update_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS market_state_snapshots (
                    as_of TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS asset_recommendations (
                    as_of TEXT NOT NULL,
                    asset TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    PRIMARY KEY (as_of, asset)
                );
                """
            )

    def save_interpretation(self, item: MarketInterpretation) -> None:
        payload = json.dumps(item.to_record(), sort_keys=True)
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO market_interpretations(
                    event_id,
                    cluster_id,
                    published_at,
                    update_type,
                    payload_json
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(event_id) DO UPDATE SET
                    cluster_id=excluded.cluster_id,
                    published_at=excluded.published_at,
                    update_type=excluded.update_type,
                    payload_json=excluded.payload_json
                """,
                (
                    item.event_id,
                    item.cluster_id,
                    item.published_at,
                    item.update_type,
                    payload,
                ),
            )

    def load_interpretations(self) -> list[MarketInterpretation]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT payload_json FROM market_interpretations ORDER BY published_at"
            ).fetchall()
        return [
            MarketInterpretation.from_mapping(json.loads(row["payload_json"]))
            for row in rows
        ]

    def save_snapshot(
        self,
        state: MarketState,
        recommendations: Iterable[AssetRecommendation],
    ) -> None:
        with self._connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO market_state_snapshots(as_of, payload_json) VALUES (?, ?)",
                (state.as_of, json.dumps(state.to_record(), sort_keys=True)),
            )
            for recommendation in recommendations:
                db.execute(
                    """
                    INSERT OR REPLACE INTO asset_recommendations(as_of, asset, payload_json)
                    VALUES (?, ?, ?)
                    """,
                    (
                        state.as_of,
                        recommendation.asset,
                        json.dumps(recommendation.to_record(), sort_keys=True),
                    ),
                )
