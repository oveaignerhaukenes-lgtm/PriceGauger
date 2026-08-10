from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import json

from database import connect
from historical_engine import HistoricalAssessment


@dataclass(frozen=True, slots=True)
class HistoricalRuntimeSignal:
    assessment_id: str
    event_id: str
    market: str
    as_of: str
    direction_score: float
    confidence: float
    expected_return_pct: float | None
    interval_low_pct: float | None
    interval_high_pct: float | None
    independent_analogues: int
    status: str

    def to_record(self) -> dict:
        return asdict(self)


def signal_from_assessment(
    assessment: HistoricalAssessment,
    *,
    event_id: str,
) -> HistoricalRuntimeSignal:
    probability_up = assessment.probability_up
    directional = 0.0 if probability_up is None else max(-1.0, min(1.0, (float(probability_up) - 0.5) * 2.0))
    score = directional * max(0.0, min(1.0, float(assessment.confidence)))
    return HistoricalRuntimeSignal(
        assessment_id=assessment.assessment_id,
        event_id=str(event_id),
        market=assessment.asset,
        as_of=assessment.generated_at,
        direction_score=round(score, 6),
        confidence=max(0.0, min(1.0, float(assessment.confidence))),
        expected_return_pct=assessment.expected_return_pct,
        interval_low_pct=assessment.likely_interval_low_pct,
        interval_high_pct=assessment.likely_interval_high_pct,
        independent_analogues=int(assessment.independent_analogues),
        status=assessment.status,
    )


class HistoricalRuntimeSignalStore:
    """Persist event-scoped Historical Engine output for Decision State consumption."""

    def __init__(self, path: str | Path = "pricegauger.db") -> None:
        self.path = str(path)
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS historical_runtime_signals (
                    assessment_id TEXT PRIMARY KEY,
                    event_id TEXT NOT NULL,
                    market TEXT NOT NULL,
                    as_of TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_historical_runtime_event_market
                ON historical_runtime_signals(event_id, market, as_of);
                """
            )

    def _connect(self):
        return connect(self.path)

    def save(self, signal: HistoricalRuntimeSignal) -> None:
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO historical_runtime_signals(
                    assessment_id, event_id, market, as_of, payload_json
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(assessment_id) DO UPDATE SET
                    event_id=excluded.event_id,
                    market=excluded.market,
                    as_of=excluded.as_of,
                    payload_json=excluded.payload_json,
                    recorded_at=CURRENT_TIMESTAMP
                """,
                (
                    signal.assessment_id,
                    signal.event_id,
                    signal.market,
                    signal.as_of,
                    json.dumps(signal.to_record(), ensure_ascii=False, sort_keys=True),
                ),
            )

    def load_latest_for_events(
        self,
        *,
        market: str,
        event_ids: tuple[str, ...] | list[str],
    ) -> HistoricalRuntimeSignal | None:
        ids = tuple(dict.fromkeys(str(item) for item in event_ids if str(item)))
        if not ids:
            return None
        placeholders = ",".join("?" for _ in ids)
        with self._connect() as db:
            row = db.execute(
                f"""
                SELECT payload_json
                FROM historical_runtime_signals
                WHERE market=? AND event_id IN ({placeholders})
                ORDER BY as_of DESC
                LIMIT 1
                """,
                (str(market), *ids),
            ).fetchone()
        if row is None:
            return None
        return HistoricalRuntimeSignal(**json.loads(row["payload_json"]))
