from __future__ import annotations

import argparse
import logging
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from config import openai_api_key, openai_market_model
from database import connect, using_postgres
from event_resolution import CanonicalEvent, canonical_event_from_plan
from market_interpreter import MockMarketInterpreter, StructuredMarketInterpreter
from market_state_service import process_market_event
from market_state_store import MarketStateStore
from openai_market_provider import OpenAIJsonProvider
from signal_outcomes import SignalOutcomeStore, refresh_signal_outcomes, register_recommendations
from telegram_query_builder import TelegramSearchPlan, fetch_search_plans
from test_protocol import PAPER_TEST_PROTOCOL

LOGGER = logging.getLogger("pricegauger.worker")
DEFAULT_DB_PATH = "pricegauger.db"
DEFAULT_INTERVAL_SECONDS = 300


@dataclass(frozen=True, slots=True)
class WorkerRunSummary:
    fetched: int
    pending: int
    processed: int
    skipped_bootstrap: int
    outcomes_refreshed: int
    interpreter: str


class WorkerStateStore:
    """Persistent message cursor and source-scoped bootstrap state."""

    def __init__(self, path: str | Path = DEFAULT_DB_PATH) -> None:
        self.path = str(path)
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS worker_messages (
                    message_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    recorded_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS worker_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )

    def _connect(self):
        return connect(self.path)

    @staticmethod
    def _initialization_key(source_key: str | None = None) -> str:
        return "telegram_initialized" if not source_key else f"telegram_initialized:{source_key}"

    def is_initialized(self, source_key: str | None = None) -> bool:
        key = self._initialization_key(source_key)
        with self._connect() as db:
            row = db.execute(
                "SELECT value FROM worker_metadata WHERE key=?", (key,)
            ).fetchone()
        return bool(row and row["value"] == "1")

    def mark_initialized(self, source_key: str | None = None) -> None:
        key = self._initialization_key(source_key)
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO worker_metadata(key, value) VALUES (?, '1')
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """,
                (key,),
            )

    def seen(self, message_id: str) -> bool:
        with self._connect() as db:
            row = db.execute(
                "SELECT 1 AS present FROM worker_messages WHERE message_id=?",
                (str(message_id),),
            ).fetchone()
        return row is not None

    def seen_with_legacy_alias(self, message_id: str) -> bool:
        """Recognize both new channel-scoped IDs and old numeric IDs."""
        value = str(message_id)
        if self.seen(value):
            return True
        if ":" in value:
            return self.seen(value.rsplit(":", 1)[-1])
        return False

    def mark(self, message_id: str, status: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO worker_messages(message_id, status, recorded_at)
                VALUES (?, ?, ?)
                ON CONFLICT(message_id) DO UPDATE SET
                    status=excluded.status,
                    recorded_at=excluded.recorded_at
                """,
                (str(message_id), status, now),
            )


def build_interpreter():
    key = openai_api_key()
    if not key:
        return MockMarketInterpreter(), "mock-interpreter-v1"
    model = openai_market_model()
    provider = OpenAIJsonProvider(api_key=key, model_version=model)
    return StructuredMarketInterpreter(provider), model


def _message_order(plan: TelegramSearchPlan) -> tuple[str, int, str]:
    """Order chronologically where possible, then by Telegram post number."""
    raw_id = str(plan.message_id).rsplit(":", 1)[-1]
    numeric_id = int(raw_id) if raw_id.isdigit() else -1
    return (plan.published_at or "", numeric_id, str(plan.message_id))


def _pending_plans(
    plans: list[TelegramSearchPlan],
    state: WorkerStateStore,
    *,
    source_key: str | None = None,
) -> tuple[list[TelegramSearchPlan], list[TelegramSearchPlan]]:
    ordered = sorted(plans, key=_message_order)
    unseen = [plan for plan in ordered if not state.seen_with_legacy_alias(plan.message_id)]
    if state.is_initialized(source_key) or not unseen:
        return unseen, []

    # On the first run for this exact adapter/channel set, process only the
    # newest visible event and record the rest without model calls.
    newest = max(unseen, key=lambda plan: _message_order(plan)[1:])
    ignored = [plan for plan in unseen if plan is not newest]
    return [newest], ignored


def _ensure_event_timestamp(event: CanonicalEvent) -> CanonicalEvent:
    if event.published_at:
        return event
    fallback = datetime.now(timezone.utc).isoformat()
    LOGGER.warning(
        "telegram event=%s has no publication timestamp; using ingestion time=%s",
        event.event_id,
        fallback,
    )
    return replace(event, published_at=fallback)


def run_once(
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
    channel: str = "Middle_East_Spectator",
    minimum_signal: int = 2,
    plans_fetcher: Callable[..., list[TelegramSearchPlan]] = fetch_search_plans,
    interpreter=None,
    source_key: str | None = None,
) -> WorkerRunSummary:
    state = WorkerStateStore(db_path)
    market_store = MarketStateStore(db_path)
    outcome_store = SignalOutcomeStore(db_path)
    chosen_interpreter, interpreter_name = (
        (interpreter, getattr(interpreter, "model_version", interpreter.__class__.__name__))
        if interpreter is not None
        else build_interpreter()
    )

    plans = plans_fetcher(channel, minimum_signal=minimum_signal)
    pending, bootstrap_ignored = _pending_plans(
        plans, state, source_key=source_key
    )
    processed = 0

    for plan in pending:
        event = _ensure_event_timestamp(canonical_event_from_plan(plan))
        result = process_market_event(
            event,
            interpreter=chosen_interpreter,
            store=market_store,
        )
        register_recommendations(
            result.interpretation,
            result.recommendations,
            store=outcome_store,
        )
        state.mark(plan.message_id, "processed")
        processed += 1
        LOGGER.info(
            "processed telegram=%s event=%s recommendations=%s protocol=%s",
            plan.message_id,
            event.event_id,
            len(result.recommendations),
            PAPER_TEST_PROTOCOL.version,
        )

    if not state.is_initialized(source_key):
        for plan in bootstrap_ignored:
            state.mark(plan.message_id, "bootstrap_ignored")
        # A successful fetch initializes the source even if all visible posts
        # were already known under the legacy numeric-ID format.
        state.mark_initialized(source_key)

    refreshed = refresh_signal_outcomes(store=outcome_store)
    summary = WorkerRunSummary(
        fetched=len(plans),
        pending=len(pending),
        processed=processed,
        skipped_bootstrap=len(bootstrap_ignored),
        outcomes_refreshed=len(refreshed),
        interpreter=str(interpreter_name),
    )
    LOGGER.info(
        "cycle complete fetched=%s pending=%s processed=%s bootstrap_skipped=%s outcomes=%s interpreter=%s",
        summary.fetched,
        summary.pending,
        summary.processed,
        summary.skipped_bootstrap,
        summary.outcomes_refreshed,
        summary.interpreter,
    )
    return summary


def run_forever(
    *,
    interval_seconds: int = DEFAULT_INTERVAL_SECONDS,
    db_path: str | Path = DEFAULT_DB_PATH,
    channel: str = "Middle_East_Spectator",
    minimum_signal: int = 2,
) -> None:
    if interval_seconds < 30:
        raise ValueError("interval must be at least 30 seconds")

    backend = "postgresql" if using_postgres() else f"sqlite:{db_path}"
    LOGGER.info(
        "worker started interval=%ss storage=%s channel=%s protocol=%s",
        interval_seconds,
        backend,
        channel,
        PAPER_TEST_PROTOCOL.version,
    )
    while True:
        started = time.monotonic()
        try:
            run_once(
                db_path=db_path,
                channel=channel,
                minimum_signal=minimum_signal,
            )
        except KeyboardInterrupt:
            raise
        except Exception:
            LOGGER.exception("worker cycle failed; next cycle will retry")
        elapsed = time.monotonic() - started
        time.sleep(max(1.0, interval_seconds - elapsed))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PriceGauger background worker")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true", help="run one cycle and exit")
    mode.add_argument(
        "--interval",
        type=int,
        default=DEFAULT_INTERVAL_SECONDS,
        help="continuous polling interval in seconds (default: 300)",
    )
    parser.add_argument("--db", default=DEFAULT_DB_PATH, help="SQLite fallback database path")
    parser.add_argument("--channel", default="Middle_East_Spectator")
    parser.add_argument("--minimum-signal", type=int, default=2)
    parser.add_argument("--log-level", default="INFO")
    return parser


def main() -> None:
    args = _parser().parse_args()
    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if args.once:
        summary = run_once(
            db_path=args.db,
            channel=args.channel,
            minimum_signal=args.minimum_signal,
        )
        print(
            "WORKER_OK "
            f"fetched={summary.fetched} pending={summary.pending} "
            f"processed={summary.processed} bootstrap_skipped={summary.skipped_bootstrap} "
            f"outcomes={summary.outcomes_refreshed} interpreter={summary.interpreter}"
        )
        return
    run_forever(
        interval_seconds=args.interval,
        db_path=args.db,
        channel=args.channel,
        minimum_signal=args.minimum_signal,
    )


if __name__ == "__main__":
    main()
