from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from database import connect
from news_context_engine import NewsContextAssessment, news_context_from_record
from telegram_query_builder import TelegramSearchPlan


DEFAULT_CONTEXT_HEARTBEAT_SECONDS = 15 * 60


def _utc(value: str | datetime) -> datetime:
    parsed = (
        value
        if isinstance(value, datetime)
        else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    )
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class NewsContextStore:
    """Persistent latest-state store shared by the worker and Streamlit app."""

    def __init__(self, path: str | Path = "pricegauger.db") -> None:
        self.path = str(path)
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS news_context_snapshots (
                    as_of TEXT PRIMARY KEY,
                    source_channel TEXT NOT NULL,
                    source_post_count INTEGER NOT NULL,
                    coverage_end TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

    def _connect(self):
        return connect(self.path)

    def save(self, assessment: NewsContextAssessment) -> None:
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO news_context_snapshots(
                    as_of, source_channel, source_post_count, coverage_end, payload_json
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(as_of) DO UPDATE SET
                    source_channel=excluded.source_channel,
                    source_post_count=excluded.source_post_count,
                    coverage_end=excluded.coverage_end,
                    payload_json=excluded.payload_json,
                    recorded_at=CURRENT_TIMESTAMP
                """,
                (
                    assessment.as_of,
                    assessment.source_channel,
                    assessment.source_post_count,
                    assessment.coverage_end,
                    json.dumps(assessment.to_record(), ensure_ascii=False, sort_keys=True),
                ),
            )

    def load_latest(self) -> NewsContextAssessment | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT payload_json FROM news_context_snapshots ORDER BY as_of DESC LIMIT 1"
            ).fetchone()
        return None if row is None else news_context_from_record(json.loads(row["payload_json"]))

    def should_refresh(
        self,
        plans: Iterable[TelegramSearchPlan],
        *,
        now: datetime | None = None,
        heartbeat_seconds: int = DEFAULT_CONTEXT_HEARTBEAT_SECONDS,
    ) -> bool:
        rows = [item for item in plans if item.published_at]
        if not rows:
            return False
        latest = self.load_latest()
        if latest is None:
            return True
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        age = max(0.0, (current - _utc(latest.as_of)).total_seconds())
        newest_source = max(_utc(item.published_at).isoformat() for item in rows)
        source_changed = (
            len(rows) != latest.source_post_count or newest_source != latest.coverage_end
        )
        return source_changed or age >= max(60, int(heartbeat_seconds))
