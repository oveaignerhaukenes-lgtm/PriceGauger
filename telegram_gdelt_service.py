from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Callable

from gdelt_runtime import ingest_telegram_plan_with_configured_gdelt
from storage import DB_PATH
from telegram_gdelt_history import TelegramGdeltHistory, load_telegram_gdelt_history
from telegram_gdelt_pipeline import TelegramGdeltIngestionResult
from telegram_query_builder import TelegramSearchPlan, fetch_latest_search_plan


@dataclass(frozen=True, slots=True)
class LatestTelegramGdeltResult:
    plan: TelegramSearchPlan
    ingestion: TelegramGdeltIngestionResult
    history: TelegramGdeltHistory


def process_latest_telegram_with_gdelt(
    *,
    channel: str = "Middle_East_Spectator",
    lookback_days: int = 365,
    limit: int = 50,
    database_path: Path | str = DB_PATH,
    timeout: int = 30,
    today: date | None = None,
    minimum_signal: int = 2,
    plan_loader: Callable[..., TelegramSearchPlan | None] = fetch_latest_search_plan,
    ingestion_runner: Callable[..., TelegramGdeltIngestionResult] = ingest_telegram_plan_with_configured_gdelt,
) -> LatestTelegramGdeltResult | None:
    """Process the latest relevant Telegram post through the stable GDELT pipeline.

    This service coordinates existing boundaries only: Telegram retrieval, GDELT
    ingestion, persistence and read-back. It does not rank candidates, infer a
    market direction or start aggregation.
    """
    if lookback_days < 1:
        raise ValueError("lookback_days must be at least 1")

    plan = plan_loader(
        channel,
        minimum_signal=minimum_signal,
        timeout=timeout,
    )
    if plan is None:
        return None

    end = today or date.today()
    start = end - timedelta(days=lookback_days)
    ingestion = ingestion_runner(
        plan,
        date_start=start.isoformat(),
        date_end=end.isoformat(),
        limit=limit,
        database_path=database_path,
        timeout=timeout,
    )
    history = load_telegram_gdelt_history(
        plan.message_id,
        search_id=ingestion.search_id,
        database_path=database_path,
    )
    if history is None:
        raise RuntimeError("Telegram GDELT ingestion completed without persisted history")

    return LatestTelegramGdeltResult(
        plan=plan,
        ingestion=ingestion,
        history=history,
    )
