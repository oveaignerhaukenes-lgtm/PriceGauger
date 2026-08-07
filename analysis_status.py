from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from database import connect


STEP_ORDER = (
    "telegram_fetch",
    "semantic_filter",
    "telegram_scoring",
    "event_clustering",
    "information_state",
    "technical_state",
    "context_state",
    "decision_state",
    "recommendation",
    "outcome_refresh",
)

STEP_LABELS = {
    "telegram_fetch": "Telegram innhentet",
    "semantic_filter": "Semantisk filtrering",
    "telegram_scoring": "AI-vurdering av poster",
    "event_clustering": "Hendelser gruppert",
    "information_state": "Information State",
    "technical_state": "Teknisk analyse",
    "context_state": "Nyhetskontekst",
    "decision_state": "Decision State",
    "recommendation": "Anbefaling",
    "outcome_refresh": "Resultatoppfølging",
}

VALID_STATUSES = {"PENDING", "RUNNING", "COMPLETE", "SKIPPED", "FAILED"}


@dataclass(frozen=True, slots=True)
class AnalysisStepStatus:
    step_key: str
    label: str
    status: str
    detail: str
    updated_at: str


class AnalysisStatusStore:
    """Persistent worker progress shared by PostgreSQL and SQLite."""

    def __init__(self, path: str | Path = "pricegauger.db") -> None:
        self.path = str(path)
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS analysis_step_status (
                    step_key TEXT PRIMARY KEY,
                    label TEXT NOT NULL,
                    status TEXT NOT NULL,
                    detail TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )

    def _connect(self):
        return connect(self.path)

    def set(self, step_key: str, status: str, detail: str = "") -> None:
        key = str(step_key)
        normalized = str(status).upper()
        if key not in STEP_LABELS:
            raise ValueError(f"unknown analysis step: {key}")
        if normalized not in VALID_STATUSES:
            raise ValueError(f"unsupported analysis status: {normalized}")
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO analysis_step_status(step_key, label, status, detail, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(step_key) DO UPDATE SET
                    label=excluded.label,
                    status=excluded.status,
                    detail=excluded.detail,
                    updated_at=excluded.updated_at
                """,
                (key, STEP_LABELS[key], normalized, str(detail), now),
            )

    def begin_cycle(self) -> None:
        for key in STEP_ORDER:
            self.set(key, "PENDING", "Venter på workeren.")

    def fail_running(self, detail: str) -> None:
        """Close every active step after an unexpected worker-cycle failure."""
        for item in self.load():
            if item.status == "RUNNING":
                self.failed(item.step_key, detail)

    def complete(self, step_key: str, detail: str = "") -> None:
        self.set(step_key, "COMPLETE", detail)

    def running(self, step_key: str, detail: str = "") -> None:
        self.set(step_key, "RUNNING", detail)

    def failed(self, step_key: str, detail: str) -> None:
        self.set(step_key, "FAILED", detail)

    def skipped(self, step_key: str, detail: str = "") -> None:
        self.set(step_key, "SKIPPED", detail)

    def load(self) -> tuple[AnalysisStepStatus, ...]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT step_key, label, status, detail, updated_at FROM analysis_step_status"
            ).fetchall()
        by_key = {str(row["step_key"]): row for row in rows}
        result: list[AnalysisStepStatus] = []
        for key in STEP_ORDER:
            row = by_key.get(key)
            if row is None:
                result.append(
                    AnalysisStepStatus(
                        step_key=key,
                        label=STEP_LABELS[key],
                        status="PENDING",
                        detail="Ingen workerstatus lagret ennå.",
                        updated_at="",
                    )
                )
            else:
                result.append(
                    AnalysisStepStatus(
                        step_key=key,
                        label=str(row["label"]),
                        status=str(row["status"]),
                        detail=str(row["detail"]),
                        updated_at=str(row["updated_at"]),
                    )
                )
        return tuple(result)
