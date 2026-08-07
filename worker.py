from __future__ import annotations

import argparse
import logging
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import pandas as pd

from config import openai_api_key, openai_market_model
from analysis_status import AnalysisStatusStore
from database import connect, using_postgres
from event_resolution import CanonicalEvent, canonical_event_from_plan
from market_interpreter import MockMarketInterpreter, StructuredMarketInterpreter
from market_state_service import process_market_event
from market_state_store import MarketStateStore
from news_context_engine import NewsContextAssessment, OpenAINewsContextEngine
from news_context_store import NewsContextStore
from openai_market_provider import OpenAIJsonProvider
from signal_outcomes import SignalOutcomeStore, refresh_signal_outcomes, register_recommendations
from state_runtime_pipeline import process_flow_snapshot
from telegram_flow_engine import OpenAITelegramFlowScorer, TelegramFlowAssessment, aggregate_scored_posts
from telegram_flow_store import TelegramFlowStore
from telegram_query_builder import TelegramSearchPlan, fetch_search_plans
from test_protocol import PAPER_TEST_PROTOCOL

LOGGER = logging.getLogger("pricegauger.worker")
DEFAULT_DB_PATH = "pricegauger.db"
DEFAULT_INTERVAL_SECONDS = 60
FLOW_HEARTBEAT_SECONDS = 600
FLOW_SCORE_DELTA = 0.02


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

    def _connect(self):
        return connect(self.path)

    def is_initialized(self) -> bool:
        with self._connect() as db:
            row = db.execute(
                "SELECT value FROM worker_metadata WHERE key='telegram_initialized'"
            ).fetchone()
        return bool(row and row["value"] == "1")

    def mark_initialized(self) -> None:
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO worker_metadata(key, value) VALUES ('telegram_initialized', '1')
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """
            )

    def seen(self, message_id: str) -> bool:
        with self._connect() as db:
            row = db.execute(
                "SELECT 1 AS present FROM worker_messages WHERE message_id=?", (str(message_id),)
            ).fetchone()
        return row is not None

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


def _asset_map(assessment: TelegramFlowAssessment) -> dict[str, object]:
    return {item.asset: item for item in assessment.assets}


def _snapshot_is_informative(
    current: TelegramFlowAssessment,
    previous: TelegramFlowAssessment | None,
    *,
    scored_posts: int,
    heartbeat_seconds: int = FLOW_HEARTBEAT_SECONDS,
    score_delta: float = FLOW_SCORE_DELTA,
) -> tuple[bool, str]:
    if previous is None:
        return True, "first_snapshot"
    if scored_posts:
        return True, "new_posts"
    if current.post_count != previous.post_count:
        return True, "post_count_changed"
    if current.event_cluster_count != previous.event_cluster_count:
        return True, "cluster_count_changed"

    previous_assets = _asset_map(previous)
    for item in current.assets:
        prior = previous_assets.get(item.asset)
        if prior is None:
            return True, f"new_asset:{item.asset}"
        if item.direction != prior.direction:
            return True, f"direction_changed:{item.asset}"
        if item.selected_event_count != prior.selected_event_count:
            return True, f"event_count_changed:{item.asset}"
        if abs(item.flow_score - prior.flow_score) >= score_delta:
            return True, f"score_changed:{item.asset}"

    current_time = pd.Timestamp(current.as_of)
    previous_time = pd.Timestamp(previous.as_of)
    if current_time.tzinfo is None:
        current_time = current_time.tz_localize("UTC")
    if previous_time.tzinfo is None:
        previous_time = previous_time.tz_localize("UTC")
    age_seconds = max(0.0, (current_time - previous_time).total_seconds())
    if age_seconds >= heartbeat_seconds:
        return True, "heartbeat"
    return False, "no_material_change"


def _refresh_news_context(
    *,
    db_path: str | Path,
    channel: str,
    plans: list[TelegramSearchPlan],
) -> NewsContextAssessment | None:
    store = NewsContextStore(db_path)
    status = AnalysisStatusStore(db_path)
    latest = store.load_latest()
    selected = [plan for plan in plans if plan.signal_score >= 1 and plan.published_at]
    key = openai_api_key()

    if not selected:
        if latest is None:
            status.skipped("context_state", "Ingen relevante, tidsstemplete poster å analysere.")
        else:
            status.complete("context_state", "Ingen nye kildeposter; siste gyldige nyhetskontekst beholdes.")
        return latest
    if not key:
        status.skipped("context_state", "OPENAI_API_KEY mangler; nyhetskontekst ble ikke oppdatert.")
        return latest
    if not store.should_refresh(selected):
        status.complete("context_state", "Ingen ny kontekst nødvendig; siste vurdering beholdes.")
        return latest

    status.running("context_state", "Vurderer nyhetsregime over 1t / 4t / 12t / 24t / 7d.")
    try:
        context = OpenAINewsContextEngine(api_key=key).assess(selected, channel=channel)
        store.save(context)
        status.complete(
            "context_state",
            f"Nyhetskontekst oppdatert fra {context.source_post_count} poster: {context.regime_label}.",
        )
        LOGGER.info(
            "news context updated as_of=%s posts=%s regime=%s model=%s",
            context.as_of,
            context.source_post_count,
            context.regime_label,
            context.model,
        )
        return context
    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}"
        if latest is not None:
            detail += "; siste gyldige kontekst beholdes"
        status.failed("context_state", detail)
        LOGGER.exception("news context refresh failed; continuing with last valid context")
        return latest


def _refresh_telegram_flow(
    *,
    db_path: str | Path,
    channel: str,
    plans: list[TelegramSearchPlan],
) -> None:
    store = TelegramFlowStore(db_path)
    status = AnalysisStatusStore(db_path)
    key = openai_api_key()
    new_plans = [plan for plan in plans if not store.has_post(plan.message_id)]
    scored_count = 0

    if key and new_plans:
        status.running("telegram_scoring", f"AI-vurderer {min(8, len(new_plans))} nye poster.")
        # Newest visible posts are scored first; older backlog is picked up later.
        selected = new_plans[-8:]
        scorer = OpenAITelegramFlowScorer(api_key=key)
        scored = scorer.score([(channel, plan) for plan in selected])
        scored_count = store.save_posts(scored)
        LOGGER.info("telegram flow scored posts=%s model=%s", scored_count, scorer.model)
    elif new_plans:
        status.skipped("telegram_scoring", "OPENAI_API_KEY mangler; nye poster ble ikke AI-vurdert.")
        LOGGER.warning("telegram flow skipped new_posts=%s because OPENAI_API_KEY is missing", len(new_plans))
    else:
        status.complete("telegram_scoring", "Ingen nye poster å AI-vurdere.")

    status.running("semantic_filter", "Kontrollerer lagrede poster for relevans og promo-innhold.")
    stored = store.load_posts(limit=500)
    status.complete("semantic_filter", f"{len(stored)} lagrede poster kontrollert for relevans og promo-innhold.")
    if not stored:
        status.skipped("event_clustering", "Ingen godkjente poster å gruppere.")
        status.skipped("context_state", "Ingen godkjente poster å bygge nyhetskontekst fra.")
        for step in ("information_state", "technical_state", "decision_state", "recommendation"):
            status.skipped(step, "Ingen godkjente poster å analysere.")
        return

    _refresh_news_context(db_path=db_path, channel=channel, plans=plans)

    status.running("event_clustering", "Grupperer poster i hendelser og bygger samlet Telegram Flow.")
    assessment = aggregate_scored_posts(stored, as_of=datetime.now(timezone.utc))
    assessment = replace(assessment, model=openai_market_model())
    previous = store.load_latest_snapshot()
    should_save, reason = _snapshot_is_informative(
        assessment,
        previous,
        scored_posts=scored_count,
    )
    if should_save:
        store.save_snapshot(assessment, process_runtime=False)
        status.complete(
            "event_clustering",
            f"{assessment.post_count} poster gruppert i {assessment.event_cluster_count} klynger.",
        )
        LOGGER.info(
            "telegram flow snapshot as_of=%s posts=%s clusters=%s reason=%s",
            assessment.as_of,
            assessment.post_count,
            assessment.event_cluster_count,
            reason,
        )
    else:
        status.complete(
            "event_clustering",
            f"Ingen vesentlig endring; {assessment.post_count} poster i {assessment.event_cluster_count} klynger.",
        )
        LOGGER.info(
            "telegram flow snapshot skipped reason=%s posts=%s clusters=%s",
            reason,
            assessment.post_count,
            assessment.event_cluster_count,
        )

    # The persistent runtime is authoritative. Run it even when the flow snapshot
    # itself is unchanged so a new deployment can bootstrap missing Decision State.
    try:
        status.running("information_state", "Kontrollerer og oppdaterer samlet Information State.")
        status.running("technical_state", "Kontrollerer prisdata og teknisk regime.")
        status.running("decision_state", "Avventer oppdatert informasjons- og teknisk state.")
        status.running("recommendation", "Avventer oppdatert Decision State.")
        process_flow_snapshot(db_path=db_path, assessment=assessment, posts=stored)
        # A successful runtime call must never leave a spinner behind. Individual
        # runtime stages normally close their own status; this guard makes every
        # successful return terminal, including no-material-change/bootstrap paths.
        terminal = {
            "information_state": ("complete", "Information State kontrollert."),
            "technical_state": ("skipped", "Ingen ny teknisk analyse nødvendig."),
            "decision_state": ("complete", "Decision State kontrollert; siste state beholdes."),
            "recommendation": ("complete", "Anbefaling kontrollert; siste vurdering beholdes."),
        }
        current = {item.step_key: item for item in status.load()}
        for step, (method, detail) in terminal.items():
            if current[step].status == "RUNNING":
                getattr(status, method)(step, detail)
    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}"
        for step in ("information_state", "technical_state", "decision_state", "recommendation"):
            current = {item.step_key: item for item in status.load()}[step]
            if current.status == "RUNNING":
                status.failed(step, detail)
        LOGGER.exception("state runtime failed; Telegram Flow remains available")


def run_once(
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
    channel: str = "Middle_East_Spectator",
    minimum_signal: int = 2,
    plans_fetcher: Callable[..., list[TelegramSearchPlan]] = fetch_search_plans,
    interpreter=None,
) -> WorkerRunSummary:
    status = AnalysisStatusStore(db_path)
    status.begin_cycle()
    status.running("telegram_fetch", f"Henter poster fra {channel}.")
    state = WorkerStateStore(db_path)
    market_store = MarketStateStore(db_path)
    outcome_store = SignalOutcomeStore(db_path)
    chosen_interpreter, interpreter_name = (
        (interpreter, getattr(interpreter, "model_version", interpreter.__class__.__name__))
        if interpreter is not None
        else build_interpreter()
    )

    try:
        # Fetch every text post for Telegram Flow. The old rule-based path still
        # receives only plans that meet minimum_signal below.
        all_plans = plans_fetcher(channel, minimum_signal=0)
        status.complete("telegram_fetch", f"{len(all_plans)} poster hentet fra Telegram.")
    except Exception as exc:
        status.failed("telegram_fetch", f"{type(exc).__name__}: {exc}")
        LOGGER.warning("telegram fetch failed; continuing with stored data: %s", exc)
        all_plans = []

    legacy_plans = [plan for plan in all_plans if plan.signal_score >= minimum_signal]
    pending, bootstrap_ignored = _pending_plans(legacy_plans, state)
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

    if not state.is_initialized() and (processed or not legacy_plans):
        for plan in bootstrap_ignored:
            state.mark(plan.message_id, "bootstrap_ignored")
        state.mark_initialized()

    _refresh_telegram_flow(db_path=db_path, channel=channel, plans=all_plans)
    status.running("outcome_refresh", "Oppdaterer resultatene for tidligere anbefalinger.")
    try:
        refreshed = refresh_signal_outcomes(store=outcome_store)
        status.complete("outcome_refresh", f"{len(refreshed)} resultater kontrollert eller oppdatert.")
    except Exception as exc:
        status.failed("outcome_refresh", f"{type(exc).__name__}: {exc}")
        raise
    summary = WorkerRunSummary(
        fetched=len(all_plans),
        pending=len(pending),
        processed=processed,
        skipped_bootstrap=len(bootstrap_ignored),
        outcomes_refreshed=len(refreshed),
        interpreter=str(interpreter_name),
    )
    LOGGER.info(
        "cycle complete fetched=%s relevant=%s pending=%s processed=%s bootstrap_skipped=%s outcomes=%s interpreter=%s",
        summary.fetched,
        len(legacy_plans),
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
        except Exception as exc:
            AnalysisStatusStore(db_path).fail_running(f"{type(exc).__name__}: {exc}")
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
        help="continuous polling interval in seconds (default: 60)",
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
