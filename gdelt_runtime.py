from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from config import (
    bigquery_max_bytes_billed,
    bigquery_project_id,
    gdelt_api_key,
    gdelt_provider,
)
from gdelt_bigquery_client import BigQueryGdeltClient
from gdelt_client import DIRECT_SENTINEL, GdeltClient
from storage import DB_PATH
from telegram_gdelt_pipeline import (
    TelegramGdeltIngestionResult,
    ingest_telegram_plan_to_gdelt,
)
from telegram_query_builder import TelegramSearchPlan


@dataclass(frozen=True, slots=True)
class ConfiguredGdeltProvider:
    client: Any
    provider_name: str
    provider_mode: str


def build_configured_gdelt_provider(
    *,
    provider_loader: Callable[[], str] = gdelt_provider,
    api_key_loader: Callable[[], str] = gdelt_api_key,
    bigquery_project_loader: Callable[[], str] = bigquery_project_id,
    bigquery_max_bytes_loader: Callable[[], int] = bigquery_max_bytes_billed,
    timeout: int = 30,
) -> ConfiguredGdeltProvider:
    """Build the configured GDELT data provider without starting any analysis.

    `bigquery` uses Google's public partitioned GDELT tables with a dry run and
    a hard byte ceiling. `direct` uses the free DOC API. `cloud` requires a
    bearer token. `auto` follows the value returned by `gdelt_api_key()`.
    """
    mode = (provider_loader() or "bigquery").strip().lower()
    if mode == "bigquery":
        return ConfiguredGdeltProvider(
            client=BigQueryGdeltClient(
                project=bigquery_project_loader(),
                maximum_bytes_billed=bigquery_max_bytes_loader(),
            ),
            provider_name="GDELT BigQuery",
            provider_mode="bigquery",
        )

    api_key = (api_key_loader() or "").strip()
    if mode == "cloud" and not api_key:
        raise ValueError("GDELT Cloud is selected but GDELT_CLOUD_API_KEY is missing")
    if not api_key:
        api_key = DIRECT_SENTINEL

    effective_mode = "direct" if api_key == DIRECT_SENTINEL else "cloud"
    provider_name = "GDELT DOC" if effective_mode == "direct" else "GDELT Cloud"
    return ConfiguredGdeltProvider(
        client=GdeltClient(api_key=api_key, timeout=timeout),
        provider_name=provider_name,
        provider_mode=effective_mode,
    )


def ingest_telegram_plan_with_configured_gdelt(
    plan: TelegramSearchPlan,
    *,
    date_start: str,
    date_end: str,
    limit: int = 50,
    database_path: Path | str = DB_PATH,
    retrieved_at: datetime | None = None,
    timeout: int = 30,
    provider_loader: Callable[[], str] = gdelt_provider,
    api_key_loader: Callable[[], str] = gdelt_api_key,
    bigquery_project_loader: Callable[[], str] = bigquery_project_id,
    bigquery_max_bytes_loader: Callable[[], int] = bigquery_max_bytes_billed,
) -> TelegramGdeltIngestionResult:
    """Run the established Telegram→GDELT→SQLite pipeline using configuration."""
    configured = build_configured_gdelt_provider(
        provider_loader=provider_loader,
        api_key_loader=api_key_loader,
        bigquery_project_loader=bigquery_project_loader,
        bigquery_max_bytes_loader=bigquery_max_bytes_loader,
        timeout=timeout,
    )
    return ingest_telegram_plan_to_gdelt(
        plan,
        configured.client,
        provider_name=configured.provider_name,
        date_start=date_start,
        date_end=date_end,
        limit=limit,
        database_path=database_path,
        retrieved_at=retrieved_at,
    )
