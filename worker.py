from __future__ import annotations

import argparse
import logging
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

from config import openai_api_key, openai_market_model
from event_resolution import canonical_event_from_plan
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
    """Small persistent cursor store independent of Streamlit sessions."""

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

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def is_initialized(self) -> bool:
        with self._connect() as db:
            row = db.execute(
                "SELECT value FROM worker_metadata WHERE key='telegram_initialized'"
            ).fetchone()
        return bool(row and row["value"] == "1")

    def mark_initialized(self) -> None:
        with self._connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO worker_metadata(key, value) VALUES ('telegram_initialized', '1')"
            )

    def seen(self, message_id: str) -> bool:
        with self._connect() as db:
            row = db.execute(
                "SELECT 1 FROM worker_messages WHERE message_id=?", (str(message_id),)
            ).fetchone()
        return row is not None

    def mark(self, message_id: str, status: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as db:
            db.execute(
                """
                INSERT OR REPLACE INTO worker_messages(message_id, status, recorded_at)
                VALUES (?, ?, ?)
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


def _pending_plans(
    plans: list[TelegramSearchPlan],
    state: WorkerStateStore,
) -> tuple[list[TelegramSearchPlan], list[TelegramSearchPlan]]:
    unseen = [plan for plan in plans if not state.seen(plan.message_id)]
    if state.is_initialized() or not unseen:
        return unseen, []

    # Bootstrap deliberately processes only the newest currently visible event.
    # This avoids a burst of historical OpenAI calls on first deployment.
    return [unseen[-1]], unseen[:-1]


def run_once(
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
    channel: str = "Middle_East_Spectator",
    minimum_signal: int = 2,
    plans_fetcher: Callable[..., list[TelegramSearchPlan]] = fetch_search_plans,
    interpreter=None,
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
    pending, bootstrap_ignored = _pending_plans(plans, state)
    processed = 0

    for plan in pending:
        event = canonical_event_from_plan(plan)
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

    if not state.is_initialized() and (processed or not plans):
        for plan in bootstrap_ignored:
            state.mark(plan.message_id, "bootstrap_ignored")
        state.mark_initialized()

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

    LOGGER.info(
        "worker started interval=%ss db=%s channel=%s protocol=%s",
        interval_seconds,
        db_path,
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
    parser.add_argument("--db", default=DEFAULT_DB_PATH, help="SQLite database path")
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
