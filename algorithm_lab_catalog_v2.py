"""Algorithm Lab permissioned, point-in-time market data catalog.

Only explicit SELECT adapters against known tables. No SQL/text from the
assistant or a user is ever interpolated. Account and private Saxo data are
intentionally not accessible to model-generation requests.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Sequence

from algorithm_lab_v1 import utc
from database import connect

MAX_CONTEXT = 200
DATASETS = (
    {"key": "ohlc_1m", "label": "Saxo UIC 1m OHLC", "resolution": "1m",
     "classification": "market", "asof": "bar end <= query time", "max_rows": 12000},
    {"key": "bbo_1s", "label": "Lagrede Saxo bid/ask", "resolution": "observed 1s",
     "classification": "market", "asof": "quote timestamp <= query time", "max_rows": 18000},
    {"key": "macro_schedule", "label": "Registrert makrokalender", "resolution": "event",
     "classification": "context", "asof": "seen_at <= query time", "max_rows": MAX_CONTEXT},
    {"key": "news_context", "label": "Historiske nyhetskontekster", "resolution": "snapshot",
     "classification": "context", "asof": "recorded_at/as_of <= query time", "max_rows": MAX_CONTEXT},
    {"key": "accounts", "label": "Saxo kontohistorikk", "resolution": "account",
     "classification": "private", "asof": "requires explicit account permission", "max_rows": 0},
)


@dataclass(frozen=True)
class CatalogResult:
    dataset: str
    as_of: str
    rows: tuple[dict, ...]
    coverage: str
    limitations: tuple[str, ...]


def catalog_manifest() -> tuple[dict, ...]:
    return tuple(dict(x) for x in DATASETS)


def catalog_context(*, dataset: str, as_of, start=None, instrument_uic: int | None = None,
                    limit: int = MAX_CONTEXT, db_path="pricegauger.db") -> CatalogResult:
    """Bounded, as-of known context. Caller may only select listed datasets."""
    key = str(dataset)
    if key not in ("macro_schedule", "news_context"):
        raise ValueError("Context read supports only listed public-context datasets.")
    stop = utc(as_of)
    begin = utc(start) if start is not None else stop-timedelta(days=7)
    if begin > stop:
        raise ValueError("Start must be <= as_of.")
    n = int(limit)
    if not 1 <= n <= MAX_CONTEXT:
        raise ValueError("Context row limit exceeds maximum.")
    with connect(db_path) as db:
        try:
            if key == "macro_schedule":
                # Events scheduled in [start, stop], and recorded before stop.
                data = db.execute(
                    """SELECT event_id, scheduled_at, seen_at, event_type,
                              importance, source, source_url
                       FROM lsim_ctx_macro_events
                       WHERE scheduled_at >= ? AND scheduled_at <= ? AND seen_at <= ?
                       ORDER BY scheduled_at, event_id LIMIT ?""",
                    (begin.isoformat(), stop.isoformat(), stop.isoformat(), n),
                ).fetchall()
                rows = tuple(dict(x) for x in data)
            else:
                # Restrict to descriptive metadata. Do NOT expose raw news payload
                # (it may contain user channels/private data) or load updated
                # snapshots as though they were historically available.
                data = db.execute(
                    """SELECT as_of, recorded_at, source_channel, source_post_count,
                              coverage_end
                       FROM news_context_snapshots
                       WHERE as_of >= ? AND as_of <= ? AND recorded_at <= ?
                       ORDER BY as_of DESC LIMIT ?""",
                    (begin.isoformat(), stop.isoformat(), stop.isoformat(), n),
                ).fetchall()
                rows = tuple(dict(x) for x in data)
        except Exception as exc:
            # Missing tables are not silently represented as zero events.
            return CatalogResult(key, stop.isoformat(), (), "UNAVAILABLE",
                                 (type(exc).__name__, "Context source missing; not a zero-event signal"))
    return CatalogResult(key, stop.isoformat(), rows, "RECORDED",
                         ("Latest known snapshots only; publication/recording delays apply",
                          "No PII, tokens, account identifiers or arbitrary SQL exposed"))


def catalog_asof_macro_flags(*, bar_times: Sequence, events: Sequence[dict]) -> tuple[dict, ...]:
    """Project recorded events to past 1m/1s samples, never future knowledge."""
    ordered = sorted(events, key=lambda e: utc(e["seen_at"]))
    results = []
    for stamp in bar_times:
        t = utc(stamp)
        past = tuple(e for e in ordered if utc(e["seen_at"]) <= t and
                     utc(e["scheduled_at"]) <= t)
        results.append({"at": t.isoformat(), "observed_events": len(past),
                        "last_event_type": str(past[-1]["event_type"]) if past else None})
    return tuple(results)


def enrich_research_bars(*, bars: Sequence, macro: CatalogResult,
                         news: CatalogResult) -> tuple:
    """Project only as-of permitted context to the completed 1m bar.

    Unknown dataset availability is -1, never silently 'no events'.
    No account, content, channel, token or arbitrary DB fields are sent.
    """
    from types import SimpleNamespace
    events = sorted(macro.rows, key=lambda x: utc(x["seen_at"])) if macro.coverage == "RECORDED" else ()
    reports = sorted(news.rows, key=lambda x: utc(x["recorded_at"])) if news.coverage == "RECORDED" else ()
    result=[]
    for bar in bars:
        closed = utc(bar.bar_time)+timedelta(minutes=1)
        macro_seen = sum(utc(x["seen_at"]) <= closed and
                         utc(x["scheduled_at"]) <= closed for x in events)
        eligible_news = [
            x for x in reports if utc(x["recorded_at"]) <= closed and
            utc(x["as_of"]) <= closed]
        news_count = (int(eligible_news[-1]["source_post_count"])
                      if eligible_news else -1)
        result.append(SimpleNamespace(
            bar_time=bar.bar_time,open=bar.open,high=bar.high,low=bar.low,
            close=bar.close,
            macro_count=macro_seen if macro.coverage == "RECORDED" else -1,
            news_post_count=news_count))
    return tuple(result)


__all__ = ["DATASETS", "CatalogResult", "catalog_manifest",
           "catalog_context", "catalog_asof_macro_flags", "enrich_research_bars"]
