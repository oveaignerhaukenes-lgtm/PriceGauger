from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import logging
from pathlib import Path
import threading
from typing import Callable, Iterable

from database import connect
from gdelt_runtime import ingest_telegram_plan_with_configured_gdelt
from historical_engine import build_historical_assessment
from historical_signal_store import HistoricalRuntimeSignalStore, signal_from_assessment
from saxo_analogue_reactions import measure_brent_reactions
from saxo_provider import configured_client
from semantic_analogue_ranking import rank_analogues, select_reactions_for_ranked_analogues
from telegram_ai_interpreter import interpret_search_plan
from telegram_flow_engine import ScoredTelegramPost
from telegram_query_builder import build_search_plan


LOGGER = logging.getLogger("pricegauger.historical_runtime")
RETRY_AFTER_MINUTES = 30
MINIMUM_ANALOGUES = 3
LOOKBACK_DAYS = 365
CANDIDATE_LIMIT = 10
_LOCK = threading.Lock()


@dataclass(frozen=True, slots=True)
class HistoricalAttempt:
    event_id: str
    market: str
    status: str
    attempt_count: int
    last_attempt_at: str
    detail: str


class HistoricalAttemptStore:
    """Persist dedupe/retry state for expensive historical analogue work."""

    def __init__(self, path: str | Path = "pricegauger.db") -> None:
        self.path = str(path)
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS historical_runtime_attempts (
                    event_id TEXT NOT NULL,
                    market TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    last_attempt_at TEXT NOT NULL,
                    detail TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (event_id, market)
                );
                """
            )

    def _connect(self):
        return connect(self.path)

    def load(self, *, event_id: str, market: str = "Brent") -> HistoricalAttempt | None:
        with self._connect() as db:
            row = db.execute(
                """
                SELECT event_id, market, status, attempt_count, last_attempt_at, detail
                FROM historical_runtime_attempts
                WHERE event_id=? AND market=?
                """,
                (str(event_id), str(market)),
            ).fetchone()
        return None if row is None else HistoricalAttempt(**dict(row))

    def eligible(
        self,
        *,
        event_id: str,
        market: str = "Brent",
        now: datetime | None = None,
    ) -> bool:
        existing = self.load(event_id=event_id, market=market)
        if existing is None:
            return True
        if existing.status in {"COMPLETE", "NO_SIGNAL"}:
            return False
        current = now or datetime.now(timezone.utc)
        previous = datetime.fromisoformat(existing.last_attempt_at.replace("Z", "+00:00"))
        if previous.tzinfo is None:
            previous = previous.replace(tzinfo=timezone.utc)
        return current.astimezone(timezone.utc) - previous.astimezone(timezone.utc) >= timedelta(minutes=RETRY_AFTER_MINUTES)

    def mark(self, *, event_id: str, status: str, detail: str = "", market: str = "Brent") -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO historical_runtime_attempts(
                    event_id, market, status, attempt_count, last_attempt_at, detail
                ) VALUES (?, ?, ?, 1, ?, ?)
                ON CONFLICT(event_id, market) DO UPDATE SET
                    status=excluded.status,
                    attempt_count=historical_runtime_attempts.attempt_count + 1,
                    last_attempt_at=excluded.last_attempt_at,
                    detail=excluded.detail
                """,
                (str(event_id), str(market), str(status), now, str(detail)[:1000]),
            )


def _brent_relevance(post: ScoredTelegramPost) -> float:
    for score in post.scores:
        if score.asset == "Brent":
            return abs(float(score.direction)) * float(score.impact) * float(score.confidence)
    return 0.0


def select_historical_candidate(
    posts: Iterable[ScoredTelegramPost],
    *,
    attempts: HistoricalAttemptStore,
) -> ScoredTelegramPost | None:
    candidates = [
        post
        for post in posts
        if _brent_relevance(post) >= 0.12
        and attempts.eligible(event_id=post.message_id, market="Brent")
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda item: str(item.published_at or ""))


def _telegram_url(post: ScoredTelegramPost) -> str:
    local_id = str(post.message_id).split(":", 1)[-1]
    channel = str(post.channel).lstrip("@")
    return f"https://t.me/{channel}/{local_id}"


def process_historical_post(
    post: ScoredTelegramPost,
    *,
    db_path: str | Path = "pricegauger.db",
    plan_interpreter: Callable = interpret_search_plan,
    ingestion_runner: Callable = ingest_telegram_plan_with_configured_gdelt,
    analogue_ranker: Callable = rank_analogues,
    client_loader: Callable = configured_client,
    reaction_measure: Callable = measure_brent_reactions,
) -> str:
    """Build one event-scoped Brent historical signal; failures stay non-authoritative."""
    attempts = HistoricalAttemptStore(db_path)
    attempts.mark(event_id=post.message_id, status="RUNNING", detail="historical analysis started")
    try:
        plan = build_search_plan(
            message_id=post.message_id,
            message_url=_telegram_url(post),
            text=post.text,
            published_at=post.published_at,
        )
        plan = plan_interpreter(plan)
        end = date.today()
        ingestion = ingestion_runner(
            plan,
            date_start=(end - timedelta(days=LOOKBACK_DAYS)).isoformat(),
            date_end=end.isoformat(),
            limit=CANDIDATE_LIMIT,
            database_path=db_path,
            timeout=30,
        )
        if not ingestion.candidates:
            attempts.mark(event_id=post.message_id, status="NO_SIGNAL", detail="no GDELT candidates")
            return "NO_SIGNAL"

        ranked = analogue_ranker(plan, ingestion.candidates, limit=CANDIDATE_LIMIT)
        client = client_loader()
        if client is None:
            raise RuntimeError("Saxo client unavailable for historical reactions")
        reactions = [item.to_record() for item in reaction_measure(ingestion.candidates, client=client)]
        selection = select_reactions_for_ranked_analogues(
            reactions,
            [item.to_record() for item in ranked],
        )
        assessment = build_historical_assessment(
            selection.selected_reactions,
            source_search_id=ingestion.search_id,
            asset="Brent",
            semantic_filter_applied=True,
        )
        if assessment.independent_analogues < MINIMUM_ANALOGUES or assessment.probability_up is None:
            attempts.mark(
                event_id=post.message_id,
                status="NO_SIGNAL",
                detail=f"only {assessment.independent_analogues} usable analogue(s)",
            )
            return "NO_SIGNAL"

        signal = signal_from_assessment(assessment, event_id=post.message_id)
        HistoricalRuntimeSignalStore(db_path).save(signal)
        attempts.mark(
            event_id=post.message_id,
            status="COMPLETE",
            detail=f"{assessment.independent_analogues} analogue(s); score={signal.direction_score:+.3f}",
        )
        LOGGER.info(
            "historical runtime complete event=%s analogues=%s score=%+.3f assessment=%s",
            post.message_id,
            assessment.independent_analogues,
            signal.direction_score,
            signal.assessment_id,
        )
        return "COMPLETE"
    except Exception as exc:
        attempts.mark(
            event_id=post.message_id,
            status="FAILED",
            detail=f"{type(exc).__name__}: {exc}",
        )
        LOGGER.exception("historical runtime failed event=%s; authoritative forecast remains available", post.message_id)
        return "FAILED"


def _run_one(post: ScoredTelegramPost, db_path: str | Path) -> None:
    try:
        process_historical_post(post, db_path=db_path)
    finally:
        _LOCK.release()


def schedule_historical_runtime(
    posts: Iterable[ScoredTelegramPost],
    *,
    db_path: str | Path = "pricegauger.db",
) -> bool:
    """Schedule at most one nonblocking historical analysis for this worker process."""
    if not _LOCK.acquire(blocking=False):
        return False
    attempts = HistoricalAttemptStore(db_path)
    candidate = select_historical_candidate(posts, attempts=attempts)
    if candidate is None:
        _LOCK.release()
        return False
    thread = threading.Thread(
        target=_run_one,
        args=(candidate, db_path),
        name="pricegauger-historical-runtime",
        daemon=True,
    )
    thread.start()
    return True
