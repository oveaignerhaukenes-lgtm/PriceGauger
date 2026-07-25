from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from config import gdelt_api_key, gdelt_provider
from gdelt_client import DIRECT_SENTINEL, GdeltClient
from storage import DB_PATH
from telegram_gdelt_pipeline import (
    TelegramGdeltIngestionResult,
    ingest_telegram_plan_to_gdelt,
)
from telegram_query_builder import TelegramSearchPlan


@dataclass(frozen=True, slots=True)
class ConfiguredGdeltProvider:
    client: GdeltClient
    provider_name: str
    provider_mode: str


def build_configured_gdelt_provider(
    *,
    provider_loader: Callable[[], str] = gdelt_provider,
    api_key_loader: Callable[[], str] = gdelt_api_key,
    timeout: int = 30,
) -> ConfiguredGdeltProvider:
    """Build the configured GDELT data provider without starting any analysis.

    `direct` uses the free official DOC API. `cloud` requires a configured
    bearer token. `auto` follows the value returned by `gdelt_api_key()`.
    """
    mode = (provider_loader() or "direct").strip().lower()
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
) -> TelegramGdeltIngestionResult:
    """Run the established Telegram→GDELT→SQLite pipeline using configuration."""
    configured = build_configured_gdelt_provider(
        provider_loader=provider_loader,
        api_key_loader=api_key_loader,
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
