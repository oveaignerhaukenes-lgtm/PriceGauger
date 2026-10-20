from __future__ import annotations

import argparse
from dataclasses import replace
import logging
import threading
from pathlib import Path
import time
from typing import Callable

from analysis_status import AnalysisStatusStore
from context_worker_bridge_v2 import publish_latest_context_v2
from telegram_channel_store import TelegramChannelStore
from telegram_flow_engine import OpenAITelegramFlowScorer
from telegram_query_builder import TelegramSearchPlan, fetch_search_plans
import worker as worker_module


LOGGER = logging.getLogger("pricegauger.telegram_multi_worker")


def _namespace_plan(channel: str, plan: TelegramSearchPlan) -> TelegramSearchPlan:
    prefix = f"{channel}:"
    message_id = str(plan.message_id)
    if message_id.startswith(prefix):
        return plan
    return replace(plan, message_id=f"{channel}:{message_id}")


def _source_aware_pairs(
    posts: list[tuple[str, TelegramSearchPlan]],
) -> list[tuple[str, TelegramSearchPlan]]:
    resolved: list[tuple[str, TelegramSearchPlan]] = []
    for fallback_channel, plan in posts:
        message_id = str(plan.message_id)
        source_channel = fallback_channel
        if ":" in message_id:
            candidate, _ = message_id.split(":", 1)
            if candidate:
                source_channel = candidate
        resolved.append((source_channel, plan))
    return resolved


class SourceAwareTelegramFlowScorer(OpenAITelegramFlowScorer):
    """Recover the real source channel from namespaced message ids."""

    def score(self, posts: list[tuple[str, TelegramSearchPlan]]):
        return super().score(_source_aware_pairs(posts))


def collect_configured_search_plans(
    store: TelegramChannelStore,
    *,
    timeout: int = 30,
    fetcher: Callable[..., list[TelegramSearchPlan]] = fetch_search_plans,
) -> list[TelegramSearchPlan]:
    """Collect every configured source before semantic scoring.

    Source-level signal filtering is deliberately disabled here. The canonical
    Bias/Context ingestion path needs the complete configured source stream so
    downstream analysis, rather than the transport layer, decides relevance.
    """
    collected: list[TelegramSearchPlan] = []
    for channel in store.list_enabled():
        try:
            plans = fetcher(channel, minimum_signal=0, timeout=timeout)
        except Exception as exc:
            LOGGER.warning("telegram channel fetch failed channel=%s: %s", channel, exc)
            continue
        collected.extend(_namespace_plan(channel, plan) for plan in plans)

    def sort_key(plan: TelegramSearchPlan) -> tuple[str, str]:
        return str(plan.published_at or ""), str(plan.message_id)

    return sorted(collected, key=sort_key)


def run_once(
    *,
    db_path: str | Path = worker_module.DEFAULT_DB_PATH,
):
    channel_store = TelegramChannelStore(db_path)

    def configured_fetcher(_channel: str, *, minimum_signal: int, timeout: int = 30):
        # worker.run_once requests the unfiltered source stream explicitly.
        if minimum_signal != 0:
            raise ValueError("configured source ingestion requires minimum_signal=0")
        return collect_configured_search_plans(
            channel_store,
            timeout=timeout,
        )

    # worker.py owns source ingestion plus the current Telegram/news semantic
    # engines. Replace only the scorer class so namespaced posts retain their
    # real configured source identity. No legacy Information/Decision runtime
    # is invoked from this path.
    original_scorer = worker_module.OpenAITelegramFlowScorer
    worker_module.OpenAITelegramFlowScorer = SourceAwareTelegramFlowScorer
    try:
        result = worker_module.run_once(
            db_path=db_path,
            channel="configured-sources",
            plans_fetcher=configured_fetcher,
            include_v3_live=False,
        )
    finally:
        worker_module.OpenAITelegramFlowScorer = original_scorer

    # Context v2 is the independent public semantic output. The bridge consumes
    # stored semantic outputs only; it cannot call Technical Core, legacy
    # Decision/Recommendation, Composer, an LLM, or execution.
    try:
        snapshot, persisted = publish_latest_context_v2(db_path=db_path)
        if snapshot is not None:
            LOGGER.info(
                "context v2 publication snapshot=%s freshness=%s persisted=%s",
                snapshot.snapshot_id,
                snapshot.freshness_status,
                persisted,
            )
    except Exception:
        LOGGER.exception("context v2 publication failed; stored semantic outputs remain available")

    return result


def _account_truth_loop_v1(*,stop_event:threading.Event,db_path:str|Path) -> None:
    """Independent five-minute Saxo GET telemetry; never blocks LIVE execution."""
    from autotrader_saxo_account_truth_v1 import (
        COLLECTION_SECONDS,collect_saxo_account_truth_once_v1,
    )
    from autotrader_saxo_official_performance_v1 import collect_official_performance_once_v1
    next_official_check=0.0
    while not stop_event.is_set():
        try:
            result=collect_saxo_account_truth_once_v1(db_path=str(db_path))
            LOGGER.info("saxo account truth status=%s seen=%s saved=%s failed=%s error_codes=%s",
                result["status"],result["seen"],result["saved"],result["failed"],
                result.get("errors",{}))
        except Exception as exc:
            # No broker exception/payload/credentials in logs.
            LOGGER.warning("saxo account truth snapshot failed kind=%s",type(exc).__name__)
        if time.monotonic()>=next_official_check and not stop_event.is_set():
            try:
                history=collect_official_performance_once_v1(db_path=str(db_path))
                LOGGER.info("saxo official EOD performance status=%s seen=%s saved=%s skipped_no_history=%s failed=%s error_codes=%s",
                    history["status"],history["seen"],history["saved"],
                    history.get("skipped_no_history",0),history["failed"],
                    history.get("errors",{}))
                next_official_check=time.monotonic()+(
                    24*3600 if history["status"]=="OK" else 3600)
            except Exception as exc:
                LOGGER.warning("saxo official EOD performance failed kind=%s",type(exc).__name__)
                next_official_check=time.monotonic()+3600
        # Sidecar consumes only durable broker snapshots and reconciled
        # orders. It never calls Saxo or touches V3 trading authority.
        try:
            from autotrader_account_learning_v1 import run_account_learning_cycle_v1
            learning=run_account_learning_cycle_v1(db_path=str(db_path))
            if learning["watched_accounts"]:
                LOGGER.info(
                    "account learning observers=%s samples=%s new_findings=%s errors=%s",
                    learning["watched_accounts"],learning["samples"],
                    learning["new_findings"],learning["errors"],
                )
        except Exception as exc:
            LOGGER.warning("account learning cycle failed kind=%s",type(exc).__name__)
        stop_event.wait(COLLECTION_SECONDS)


def run_forever(
    *,
    interval_seconds: int = worker_module.DEFAULT_INTERVAL_SECONDS,
    db_path: str | Path = worker_module.DEFAULT_DB_PATH,
) -> None:
    if interval_seconds < 30:
        raise ValueError("interval must be at least 30 seconds")

    channel_store = TelegramChannelStore(db_path)
    LOGGER.info(
        "multi-channel worker started interval=%ss channels=%s",
        interval_seconds,
        ",".join(channel_store.list_enabled()) or "none",
    )
    stop_event=threading.Event()
    v3_thread=threading.Thread(
        target=worker_module.run_v3_live_fast_loop_v1,
        kwargs={
            "db_path":db_path,
            "stop_event":stop_event,
            "interval_seconds":worker_module.V3_LIVE_INTERVAL_SECONDS,
        },
        name="pricegauger-v3-live",
        daemon=True,
    )
    v3_thread.start()
    telemetry_thread=threading.Thread(
        target=_account_truth_loop_v1,
        kwargs={"stop_event":stop_event,"db_path":db_path},
        name="pricegauger-saxo-account-truth",
        daemon=True,
    )
    telemetry_thread.start()
    # Separate, rate-bounded read-only AI shadow observer. No Saxo POST or
    # mutation of V3 target/order state; failures cannot block the LIVE loop.
    from autotrader_v3_ai_manager_shadow_v1 import run_v3_ai_shadow_forever_v1
    ai_shadow_thread=threading.Thread(
        target=run_v3_ai_shadow_forever_v1,
        kwargs={"db_path":str(db_path),"stop_event":stop_event},
        name="pricegauger-v3-ai-shadow",
        daemon=True,
    )
    ai_shadow_thread.start()
    while True:
        started = time.monotonic()
        try:
            run_once(db_path=db_path)
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            AnalysisStatusStore(db_path).fail_running(f"{type(exc).__name__}: {exc}")
            LOGGER.exception("multi-channel worker cycle failed; next cycle will retry")
        elapsed = time.monotonic() - started
        time.sleep(max(1.0, interval_seconds - elapsed))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PriceGauger multi-channel Telegram worker")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true", help="run one cycle and exit")
    mode.add_argument(
        "--interval",
        type=int,
        default=worker_module.DEFAULT_INTERVAL_SECONDS,
        help="continuous polling interval in seconds (default: 60)",
    )
    parser.add_argument("--db", default=worker_module.DEFAULT_DB_PATH, help="SQLite fallback database path")
    parser.add_argument("--log-level", default="INFO")
    return parser


def main() -> None:
    args = _parser().parse_args()
    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    if args.once:
        run_once(db_path=args.db)
        return
    run_forever(
        interval_seconds=args.interval,
        db_path=args.db,
    )


if __name__ == "__main__":
    main()