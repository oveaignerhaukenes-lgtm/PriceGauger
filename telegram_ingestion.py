from __future__ import annotations

import asyncio
from collections.abc import Sequence

from telegram_query_builder import TelegramSearchPlan, build_search_plan
from telegram_sources import MessageSource, build_telegram_source


def plans_from_messages(
    messages,
    *,
    minimum_signal: int = 2,
) -> list[TelegramSearchPlan]:
    plans: list[TelegramSearchPlan] = []
    for message in messages:
        plan = build_search_plan(
            message_id=str(message.message_id),
            message_url=message.message_url,
            text=message.text,
            published_at=message.published_at,
        )
        if plan.signal_score >= minimum_signal and plan.search:
            plans.append(plan)
    return plans


async def fetch_plans(
    source: MessageSource,
    *,
    minimum_signal: int = 2,
) -> list[TelegramSearchPlan]:
    return plans_from_messages(
        await source.fetch(),
        minimum_signal=minimum_signal,
    )


def fetch_search_plans_from_source(
    channels: str | Sequence[str],
    *,
    mode: str = "web",
    minimum_signal: int = 2,
    **source_options,
) -> list[TelegramSearchPlan]:
    source = build_telegram_source(mode, channels, **source_options)
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(fetch_plans(source, minimum_signal=minimum_signal))
    raise RuntimeError(
        "fetch_search_plans_from_source cannot run inside an active event loop; "
        "await fetch_plans(...) instead"
    )
