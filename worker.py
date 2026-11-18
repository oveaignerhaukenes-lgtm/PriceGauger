from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import logging
import threading
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import pandas as pd

from analysis_status import AnalysisStatusStore
from background_ai_policy_v1 import background_ai_enabled_v1
from autotrader_ai_baseline_v1 import run_ai_baseline_shadow_once_v1
from autotrader_strategy_series_materializer_v1 import materialize_strategy_series_once_v1
from autotrader_v3_sim_runtime_v1 import run_v3_sim_cycle_v1
from autotrader_v3_fleet_observer_v1 import run_monitor_once
from autotrader_v3_live_runtime_v1 import (
    owned_live_account_routes_v3, run_v3_live_cycle_v1,
)
from config import openai_api_key, openai_market_model
from database import using_postgres, v3_postgres_pool_scope
from v3_runtime_timing_v1 import record_v3_phase_v1
from indicator_ai_insights_v1 import refresh_indicator_ai_once_v1
from news_context_engine import NewsContextAssessment, OpenAINewsContextEngine
from news_context_store import NewsContextStore
from telegram_flow_engine import OpenAITelegramFlowScorer, TelegramFlowAssessment, aggregate_scored_posts
from telegram_flow_store import TelegramFlowStore
from telegram_query_builder import TelegramSearchPlan, fetch_search_plans

LOGGER = logging.getLogger("pricegauger.worker")
DEFAULT_DB_PATH = "pricegauger.db"
DEFAULT_INTERVAL_SECONDS = 60
# One-second lightweight price cursor checks; expensive Saxo/account inventory
# reconciliation is rate-bounded separately. No new intrabar trading authority.
V3_LIVE_INTERVAL_SECONDS = 1
V3_LIVE_RECONCILE_SECONDS = 30
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
    if not background_ai_enabled_v1():
        status.skipped("context_state", "Automatisk nyhets-AI er deaktivert; siste lagrede kontekst beholdes.")
        return latest
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

    if background_ai_enabled_v1() and key and new_plans:
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
    elif new_plans and not background_ai_enabled_v1():
        status.skipped("telegram_scoring", "Automatisk Telegram-AI er deaktivert; råposter lagres separat.")
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
    include_v3_live: bool = True,
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

    # Preserve raw source data independently of paid semantic scoring.  This
    # path remains active with all unsolicited OpenAI requests switched off.
    try:
        saved_raw = TelegramFlowStore(db_path).save_raw_plans(all_plans, channel=channel)
        if saved_raw:
            LOGGER.info("telegram raw posts persisted=%d", saved_raw)
    except Exception as exc:
        LOGGER.warning("telegram raw archive failed; other collection continues: %s", exc)

    try:
        _refresh_telegram_flow(db_path=db_path, channel=channel, plans=all_plans)
    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}"
        status.fail_running(detail)
        LOGGER.exception("telegram/context refresh failed; next cycle will retry")

    # The AI baseline consumes only persisted context. Running it after the news/flow
    # refresh means each decision can be replayed against exactly what PG knew then.
    try:
        saved = run_ai_baseline_shadow_once_v1(db_path=str(db_path))
        if saved:
            LOGGER.info("AI baseline shadow persisted decisions=%d", saved)
    except Exception as exc:
        LOGGER.warning("AI baseline shadow refresh failed; other worker functions continue: %s", exc, exc_info=True)

    # Indicator AI is explanatory/read-model only. The persisted TradingDesk opt-in
    # is OFF by default; without it this path returns before any provider call.
    try:
        indicator_snapshots = refresh_indicator_ai_once_v1(
            api_key=openai_api_key(),
            db_path=str(db_path),
        )
        if indicator_snapshots:
            LOGGER.info("indicator AI read model persisted snapshots=%d", indicator_snapshots)
    except Exception as exc:
        LOGGER.warning("indicator AI refresh failed; worker continues: %s", exc, exc_info=True)

    # Migration bridge: expensive strategy replay happens once in the background, not
    # in TradingDesk. The resulting common series table is the stable interface that
    # later native/incremental producers and the Strategy Lab chart will share.
    try:
        materialized = materialize_strategy_series_once_v1(db_path=str(db_path))
        if materialized.points_inserted or materialized.failed_products:
            LOGGER.info(
                "strategy series persisted products=%d strategies=%d inserted=%d failed=%d",
                materialized.products,
                materialized.strategies,
                materialized.points_inserted,
                materialized.failed_products,
            )
    except Exception as exc:
        LOGGER.warning("strategy series materialization failed; worker continues: %s", exc, exc_info=True)

    try:
        v3_processed = run_v3_sim_cycle_v1(db_path=str(db_path))
        if v3_processed:
            LOGGER.info("v3 SIM processed canonical closed bars=%d", v3_processed)
    except Exception as exc:
        LOGGER.warning("v3 MACD-Trailing SIM cycle failed; worker continues: %s", exc, exc_info=True)

    if include_v3_live:
        try:
            v3_live_executed = run_v3_live_cycle_v1(db_path=str(db_path))
            if v3_live_executed:
                LOGGER.info("v3 LIVE executed mutations=%d", v3_live_executed)
        except Exception as exc:
            LOGGER.warning("v3 LIVE cycle failed; worker continues: %s", exc, exc_info=True)

    try:
        observed=run_monitor_once(db_path=str(db_path))
        if any(item["severity"]=="CRITICAL" for item in observed):
            LOGGER.warning("V3 fleet observer critical=%d",
                sum(item["severity"]=="CRITICAL" for item in observed))
    except Exception as exc:
        LOGGER.warning("V3 fleet observer unavailable kind=%s",
                       type(exc).__name__)

    summary = WorkerRunSummary(fetched=len(all_plans))
    LOGGER.info("cycle complete fetched=%s", summary.fetched)
    return summary


def _run_v3_live_pooled_account_v1(**kwargs):
    """Scope PostgreSQL pooling to this task, preserving per-account isolation."""
    with v3_postgres_pool_scope():
        return run_v3_live_cycle_v1(**kwargs)


def run_v3_live_fast_loop_v1(
    *,
    db_path: str | Path,
    stop_event: threading.Event,
    interval_seconds: int = V3_LIVE_INTERVAL_SECONDS,
) -> None:
    """Run armed accounts independently, never two cycles on one Saxo account.

    Fast-quote accounts get dedicated workers so a slow closed-bar account
    cannot delay their broker-backed decisions. Account-specific Saxo sessions,
    explicit LIVE ownership and durable reservations remain mandatory.
    """
    from autotrader_v3_live_bar_watcher_v1 import (
        closed_instrument_cursors_v3, has_new_closed_bar_v3,
    )
    from autotrader_v3_whipsaw_optin_b_20261013 import apply_authorized_whipsaw_b_once

    interval=max(1.0,float(interval_seconds))
    reconciliation=float(V3_LIVE_RECONCILE_SECONDS)
    last_cycle_at=None
    last_closed=()
    last_hyper_quotes=()
    last_hyper_quality_at=0.0
    errors_at=0.0
    route_refresh_at=float('-inf')
    routes={}
    running={}
    running_started={}
    queued={}
    LOGGER.info(
        "v3 LIVE concurrent account watch started poll=%ss reconciliation=%ss fast_workers=6 bar_workers=6",
        interval,reconciliation,
    )
    with (ThreadPoolExecutor(max_workers=6,thread_name_prefix='v3-quote') as fast_pool,
          ThreadPoolExecutor(max_workers=6,thread_name_prefix='v3-bars') as bar_pool):
        def dispatch(account_id, *, quote_only):
            # A separate Saxo client/session is constructed inside each task.
            pool=fast_pool if routes[account_id] else bar_pool
            running_started[account_id]=time.monotonic()
            running[account_id]=pool.submit(
                _run_v3_live_pooled_account_v1,db_path=str(db_path),
                hyper_quote_only=quote_only,account_ids=(account_id,))

        while not stop_event.is_set():
            started=time.monotonic()
            for account_id,future in tuple(running.items()):
                if not future.done():
                    continue
                del running[account_id]
                elapsed=time.monotonic()-running_started.pop(account_id,started)
                record_v3_phase_v1('account_cycle',elapsed)
                if elapsed>=5:
                    LOGGER.warning('v3 LIVE account cycle slow account_suffix=%s elapsed_s=%.2f',
                                   str(account_id)[-4:],elapsed)
                try:
                    executed=future.result()
                    if executed:
                        LOGGER.info('v3 LIVE account=%s executed mutations=%d',
                                    str(account_id)[-4:],executed)
                except Exception as exc:
                    LOGGER.warning('v3 LIVE account=%s cycle failed kind=%s',
                                   str(account_id)[-4:],type(exc).__name__,exc_info=True)
                if account_id in queued:
                    full=queued.pop(account_id)
                    if account_id in routes:
                        dispatch(account_id,quote_only=not full)

            newly_routed=()
            if started-route_refresh_at>=5:
                route_refresh_at=started
                try:
                    updated=owned_live_account_routes_v3(db_path=str(db_path))
                    newly_routed=tuple(set(updated)-set(routes))
                    routes=updated
                except Exception as exc:
                    # No cached authorization may schedule new broker work
                    # when fresh account-ownership checks are unavailable.
                    routes={}
                    queued.clear()
                    if started-errors_at>=60:
                        LOGGER.warning('v3 LIVE account route unavailable kind=%s',
                                       type(exc).__name__)
                        errors_at=started
            changed=False
            try:
                current=closed_instrument_cursors_v3(db_path=str(db_path))
                changed=has_new_closed_bar_v3(last_closed,current)
                last_closed=current
            except Exception as exc:
                if started-errors_at>=60:
                    LOGGER.warning('v3 LIVE closed-bar watcher unavailable kind=%s',
                                   type(exc).__name__)
                    errors_at=started
            quote_changed=False
            try:
                from autotrader_v3_hyper_chase_live_v1 import live_hyper_quote_cursors_v3
                current_hyper=live_hyper_quote_cursors_v3(db_path=str(db_path))
                old_hyper=dict(last_hyper_quotes)
                quote_changed=any(
                    stamp!=old_hyper.get(uic) for uic,stamp in current_hyper)
                last_hyper_quotes=current_hyper
            except Exception as exc:
                if started-errors_at>=60:
                    LOGGER.warning('v3 hyper quote wake unavailable kind=%s',
                                   type(exc).__name__)
                    errors_at=started
            if started-last_hyper_quality_at>=60:
                last_hyper_quality_at=started
                try:
                    from hyper_chase_quote_quality_probe_v1 import probe_hyper_quote_quality_v1
                    quality=probe_hyper_quote_quality_v1(db_path=str(db_path))
                    if not quality:
                        LOGGER.info('hyper chase BBO QUALITY no_valid_recent_samples')
                    for sample in quality:
                        LOGGER.info(
                            'hyper chase BBO QUALITY uic=%d quotes_60s=%d '
                            'latest_age_s=%s max_gap_s=%s wide_spread_quotes=%d '
                            'valid_10s_windows=%d',
                            sample['uic'],sample['quotes_60s'],sample['latest_age_s'],
                            sample['max_gap_s'],sample['wide_spread_quotes'],
                            sample['valid_10s_windows'])
                except Exception as exc:
                    LOGGER.warning('hyper chase BBO QUALITY unavailable error_type=%s',
                                   type(exc).__name__)
            heartbeat=(last_cycle_at is None or started-last_cycle_at>=reconciliation)
            full=changed or heartbeat
            if full or quote_changed or newly_routed:
                if full:
                    last_cycle_at=started
                    if changed:
                        LOGGER.info('v3 LIVE canonical closed-bar advanced; evaluating now')
                if full or newly_routed:
                    try:
                        apply_authorized_whipsaw_b_once(db_path=str(db_path))
                    except Exception as exc:
                        LOGGER.warning('Tech100-B LIVE whipsaw opt-in deferred error_type=%s',
                                       type(exc).__name__)
                selected=(set(routes) if full else
                          {aid for aid,is_fast in routes.items() if is_fast}
                          if quote_changed else set()) | set(newly_routed)
                # Fast accounts always receive worker slots independently of
                # slow bar accounts; within an account, never overlap cycles.
                for account_id in sorted(selected,key=lambda aid:(not routes[aid],aid)):
                    wants_full=full or account_id in newly_routed
                    if account_id in running:
                        queued[account_id]=queued.get(account_id,False) or wants_full
                    else:
                        dispatch(account_id,quote_only=not wants_full)
            remaining=max(0.1,interval-(time.monotonic()-started))
            stop_event.wait(remaining)


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
    stop_event=threading.Event()
    v3_thread=threading.Thread(
        target=run_v3_live_fast_loop_v1,
        kwargs={
            "db_path":db_path,
            "stop_event":stop_event,
            "interval_seconds":V3_LIVE_INTERVAL_SECONDS,
        },
        name="pricegauger-v3-live",
        daemon=True,
    )
    v3_thread.start()
    while True:
        started = time.monotonic()
        try:
            run_once(
                db_path=db_path,
                channel=channel,
                include_v3_live=False,
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
