from __future__ import annotations

import argparse
import logging
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import pandas as pd

from analysis_status import AnalysisStatusStore
from config import openai_api_key, openai_market_model
from database import using_postgres
from news_context_engine import NewsContextAssessment, OpenAINewsContextEngine
from news_context_store import NewsContextStore
from telegram_flow_engine import OpenAITelegramFlowScorer, TelegramFlowAssessment, aggregate_scored_posts
from telegram_flow_store import TelegramFlowStore
from telegram_query_builder import TelegramSearchPlan, fetch_search_plans

LOGGER = logging.getLogger("pricegauger.worker")
DEFAULT_DB_PATH = "pricegauger.db"
DEFAULT_INTERVAL_SECONDS = 60
FLOW_HEARTBEAT_SECONDS = 600
FLOW_SCORE_DELTA = 0.02


@dataclass(frozen=True, slots=True)
class WorkerRunSummary:
    fetched: int


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
        return True, "event_cluster_count_changed"

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
        selected = new_plans[-8:]
        try:
            scorer = OpenAITelegramFlowScorer(api_key=key)
            scored = scorer.score([(channel, plan) for plan in selected])
            scored_count = store.save_posts(scored)
            status.complete("telegram_scoring", f"{scored_count} nye poster AI-vurdert.")
            LOGGER.info("telegram flow scored posts=%s model=%s", scored_count, scorer.model)
        except Exception as exc:
            detail = f"{type(exc).__name__}: {exc}; fortsetter med tidligere lagrede poster"
            status.failed("telegram_scoring", detail)
            LOGGER.exception("telegram scoring failed; continuing with stored posts")
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


def run_once(
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
    channel: str = "Middle_East_Spectator",
    plans_fetcher: Callable[..., list[TelegramSearchPlan]] = fetch_search_plans,
) -> WorkerRunSummary:
    status = AnalysisStatusStore(db_path)
    status.begin_cycle()
    status.running("telegram_fetch", f"Henter poster fra {channel}.")
    LOGGER.info("cycle started channel=%s", channel)

    try:
        all_plans = plans_fetcher(channel, minimum_signal=0)
        status.complete("telegram_fetch", f"{len(all_plans)} poster hentet fra Telegram.")
    except Exception as exc:
        status.failed("telegram_fetch", f"{type(exc).__name__}: {exc}")
        LOGGER.warning("telegram fetch failed; continuing with stored data: %s", exc)
        all_plans = []

    try:
        _refresh_telegram_flow(db_path=db_path, channel=channel, plans=all_plans)
    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}"
        status.fail_running(detail)
        LOGGER.exception("telegram/context refresh failed; next cycle will retry")

    summary = WorkerRunSummary(fetched=len(all_plans))
    LOGGER.info("cycle complete fetched=%s", summary.fetched)
    return summary


def run_forever(
    *,
    interval_seconds: int = DEFAULT_INTERVAL_SECONDS,
    db_path: str | Path = DEFAULT_DB_PATH,
    channel: str = "Middle_East_Spectator",
) -> None:
    if interval_seconds < 30:
        raise ValueError("interval must be at least 30 seconds")

    backend = "postgresql" if using_postgres() else f"sqlite:{db_path}"
    LOGGER.info("worker started interval=%ss storage=%s channel=%s", interval_seconds, backend, channel)
    while True:
        started = time.monotonic()
        try:
            run_once(
                db_path=db_path,
                channel=channel,
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
        )
        print(f"WORKER_OK fetched={summary.fetched}")
        return
    run_forever(
        interval_seconds=args.interval,
        db_path=args.db,
        channel=args.channel,
    )


if __name__ == "__main__":
    main()
