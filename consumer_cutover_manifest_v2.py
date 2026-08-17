from __future__ import annotations

from dataclasses import dataclass


CUTOVER = "CUTOVER"
TEMPORARY_ADAPTER = "TEMPORARY_ADAPTER"
RETIRE = "RETIRE"
MIXED_SURFACE = "MIXED_SURFACE"


@dataclass(frozen=True, slots=True)
class ConsumerCutoverV2:
    consumer: str
    classification: str
    canonical_source: str
    note: str


CONSUMER_CUTOVER_V2: tuple[ConsumerCutoverV2, ...] = (
    ConsumerCutoverV2(
        "Technical Core runtime",
        CUTOVER,
        "MarketHistoryStore -> pg_v2_market_bars_1m",
        "Authoritative technical production reads canonical v2 market history.",
    ),
    ConsumerCutoverV2(
        "Parallel forecast outcome runtime",
        CUTOVER,
        "MarketHistoryStore -> pg_v2_market_bars_1m",
        "Benchmark candidates resolve against the same canonical v2 history bridge.",
    ),
    ConsumerCutoverV2(
        "AutoTrader MACD dry-run",
        CUTOVER,
        "MarketHistoryStore -> pg_v2_market_bars_1m",
        "Read-only strategy evaluation consumes canonical history and v2 market identity.",
    ),
    ConsumerCutoverV2(
        "TradingDesk",
        CUTOVER,
        "v2 workspace + RealtimeMarketDataStore(v2 preferred)",
        "No hidden legacy analysis/forecast fallback after cutover.",
    ),
    ConsumerCutoverV2(
        "Overview technical cards",
        CUTOVER,
        "overview_v2_cards + v2 workspace",
        "Technical analysis and forecast cards are canonical v2.",
    ),
    ConsumerCutoverV2(
        "MarketHistoryStore historical continuity",
        TEMPORARY_ADAPTER,
        "pg_v2_market_bars_1m preferred; legacy rows only fill pre-cutover gaps",
        "Remove only after enough canonical v2 history has accumulated/backfilled.",
    ),
    ConsumerCutoverV2(
        "RealtimeMarketDataStore compatibility row",
        TEMPORARY_ADAPTER,
        "dual-write; PostgreSQL reads prefer pg_v2_market_bars_1m",
        "Retained for rollback and remaining diagnostics during first production test window.",
    ),
    ConsumerCutoverV2(
        "Overview semantic/news shell",
        MIXED_SURFACE,
        "legacy semantic stores + canonical v2 technical cards",
        "Deliberately mixed until Context-v2 source-policy/runtime migration is completed.",
    ),
    ConsumerCutoverV2(
        "Historical Event Lab",
        RETIRE,
        "legacy-only developer surface",
        "Keep isolated from production authority; remove in legacy-retirement capability.",
    ),
)


def cutover_by_consumer_v2() -> dict[str, ConsumerCutoverV2]:
    return {item.consumer: item for item in CONSUMER_CUTOVER_V2}
