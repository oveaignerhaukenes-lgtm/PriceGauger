from __future__ import annotations

import argparse
from dataclasses import replace
import logging
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
    minimum_signal: int,
    timeout: int = 30,
    fetcher: Callable[..., list[TelegramSearchPlan]] = fetch_search_plans,
) -> list[TelegramSearchPlan]:
    collected: list[TelegramSearchPlan] = []
    for channel in store.list_enabled():
        try:
            plans = fetcher(channel, minimum_signal=minimum_signal, timeout=timeout)
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
    minimum_signal: int = 2,
):
    channel_store = TelegramChannelStore(db_path)

    def configured_fetcher(_channel: str, *, minimum_signal: int, timeout: int = 30):
        return collect_configured_search_plans(
            channel_store,
            minimum_signal=minimum_signal,
            timeout=timeout,
        )

    # worker.py remains the authoritative legacy analysis/state pipeline during
    # this bounded migration step. Only replace the scorer class so it sees the
    # real channel for each namespaced source post.
    original_scorer = worker_module.OpenAITelegramFlowScorer
    worker_module.OpenAITelegramFlowScorer = SourceAwareTelegramFlowScorer
    try:
        result = worker_module.run_once(
            db_path=db_path,
            channel="configured-sources",
            minimum_signal=minimum_signal,
            plans_fetcher=configured_fetcher,
        )
    finally:
        worker_module.OpenAITelegramFlowScorer = original_scorer

    # Context v2 is an independent public output of the semantic engines. The
    # bridge consumes their stored outputs only; it cannot call Technical Core,
    # legacy Decision/Recommendation, Composer, an LLM, or execution.
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
        # Context-v2 publication must not make the existing ingestion daemon lose
        # the already-produced Telegram/News state while migration is in progress.
        LOGGER.exception("context v2 publication failed; existing semantic outputs remain available")

    return result


def run_forever(
    *,
    interval_seconds: int = worker_module.DEFAULT_INTERVAL_SECONDS,
    db_path: str | Path = worker_module.DEFAULT_DB_PATH,
    minimum_signal: int = 2,
) -> None:
    if interval_seconds < 30:
        raise ValueError("interval must be at least 30 seconds")

    channel_store = TelegramChannelStore(db_path)
    LOGGER.info(
        "multi-channel worker started interval=%ss channels=%s",
        interval_seconds,
        ",".join(channel_store.list_enabled()) or "none",
    )
    while True:
        started = time.monotonic()
        try:
            run_once(db_path=db_path, minimum_signal=minimum_signal)
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
    parser.add_argument("--minimum-signal", type=int, default=2)
    parser.add_argument("--log-level", default="INFO")
    return parser


def main() -> None:
    args = _parser().parse_args()
    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    if args.once:
        run_once(db_path=args.db, minimum_signal=args.minimum_signal)
        return
    run_forever(
        interval_seconds=args.interval,
        db_path=args.db,
        minimum_signal=args.minimum_signal,
    )


if __name__ == "__main__":
    main()