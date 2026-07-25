from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
import re
from typing import Any
from urllib.parse import unquote, urlparse

from google.cloud import bigquery

from event_models import MarketEvent

# The GKG table contains very large free-text columns. It is appropriate for
# aggregate World State calculations, but not for a small per-event analogue
# lookup. Historical Event Lab therefore uses the much narrower Events table.
GDELT_EVENTS_TABLE = "gdelt-bq.gdeltv2.events_partitioned"
MAX_BYTES_BILLED = 512 * 1024**2
_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{2,}")
_STOPWORDS = {
    "after", "against", "amid", "and", "attack", "breaking", "from", "into",
    "near", "over", "reported", "reports", "says", "that", "the", "their",
    "this", "with", "will", "event", "news",
}


@dataclass(frozen=True, slots=True)
class BigQueryEventPage:
    events: list[MarketEvent]
    source: str = "GDELT BigQuery Events"
    warning: str | None = None
    bytes_processed: int = 0


def _keywords(search: str, country: str, *, limit: int = 6) -> list[str]:
    terms: list[str] = []
    for token in _TOKEN_RE.findall(f"{search} {country}"):
        lowered = token.lower()
        if lowered in _STOPWORDS or lowered in terms:
            continue
        terms.append(lowered)
        if len(terms) >= limit:
            break
    if not terms:
        raise ValueError("BigQuery-søket mangler brukbare nøkkelord")
    return terms


def _title_from_url(url: str, actor1: str, actor2: str, location: str) -> str:
    path = unquote(urlparse(url).path).strip("/")
    if path:
        candidate = path.rsplit("/", 1)[-1].replace("-", " ").replace("_", " ")
        candidate = " ".join(candidate.split())
        if len(candidate) >= 8:
            return candidate[:240]
    participants = " / ".join(value for value in (actor1, actor2) if value)
    return (participants or location or "GDELT historical event")[:240]


def _query() -> str:
    # Partition pruning happens before keyword matching. Only a compact set of
    # scalar columns is read; no GKG Themes/Persons/Organizations blobs are scanned.
    return f"""
    WITH candidates AS (
      SELECT
        GLOBALEVENTID AS event_id,
        TIMESTAMP_MILLIS(DATEADDED) AS published_at,
        SOURCEURL AS url,
        COALESCE(Actor1Name, '') AS actor1,
        COALESCE(Actor2Name, '') AS actor2,
        COALESCE(ActionGeo_FullName, '') AS location,
        COALESCE(ActionGeo_CountryCode, '') AS country_code,
        COALESCE(EventCode, '') AS event_code,
        COALESCE(EventBaseCode, '') AS event_base_code,
        COALESCE(EventRootCode, '') AS event_root_code,
        SAFE_CAST(GoldsteinScale AS FLOAT64) AS goldstein,
        SAFE_CAST(NumMentions AS INT64) AS mentions,
        SAFE_CAST(NumSources AS INT64) AS sources,
        SAFE_CAST(NumArticles AS INT64) AS articles,
        SAFE_CAST(AvgTone AS FLOAT64) AS tone,
        LOWER(CONCAT(
          COALESCE(Actor1Name, ''), ' ',
          COALESCE(Actor2Name, ''), ' ',
          COALESCE(ActionGeo_FullName, ''), ' ',
          COALESCE(ActionGeo_CountryCode, ''), ' ',
          COALESCE(SOURCEURL, '')
        )) AS searchable
      FROM `{GDELT_EVENTS_TABLE}`
      WHERE _PARTITIONTIME >= TIMESTAMP(@start_date)
        AND _PARTITIONTIME < TIMESTAMP(DATE_ADD(@end_date, INTERVAL 1 DAY))
    ), scored AS (
      SELECT
        *,
        (SELECT COUNTIF(STRPOS(searchable, keyword) > 0)
         FROM UNNEST(@keywords) AS keyword) AS keyword_hits
      FROM candidates
    )
    SELECT
      event_id, published_at, url, actor1, actor2, location, country_code,
      event_code, event_base_code, event_root_code, goldstein, mentions,
      sources, articles, tone, keyword_hits
    FROM scored
    WHERE keyword_hits >= @minimum_hits
    QUALIFY ROW_NUMBER() OVER (PARTITION BY url ORDER BY published_at ASC) = 1
    ORDER BY keyword_hits DESC, articles DESC, published_at DESC
    LIMIT @row_limit
    """


def fetch_bigquery_events(
    *,
    date_start: str | date,
    date_end: str | date,
    search: str,
    country: str = "",
    domain: str = "",
    event_type: str = "",
    target: str = "",
    limit: int = 50,
    client: bigquery.Client | None = None,
    maximum_bytes_billed: int = MAX_BYTES_BILLED,
) -> BigQueryEventPage:
    start = date.fromisoformat(str(date_start)) if not isinstance(date_start, date) else date_start
    end = date.fromisoformat(str(date_end)) if not isinstance(date_end, date) else date_end
    if start > end:
        raise ValueError("Fra-dato må være før eller lik til-dato")

    keywords = _keywords(search, country)
    # One strong term is enough for narrow searches; broader plans require two.
    minimum_hits = 1 if len(keywords) <= 3 else 2
    parameters = [
        bigquery.ScalarQueryParameter("start_date", "DATE", start),
        bigquery.ScalarQueryParameter("end_date", "DATE", end),
        bigquery.ArrayQueryParameter("keywords", "STRING", keywords),
        bigquery.ScalarQueryParameter("minimum_hits", "INT64", minimum_hits),
        bigquery.ScalarQueryParameter("row_limit", "INT64", max(5, min(int(limit), 100))),
    ]
    sql = _query()
    bq = client or bigquery.Client()

    dry_config = bigquery.QueryJobConfig(
        query_parameters=parameters,
        dry_run=True,
        use_query_cache=False,
    )
    dry_job = bq.query(sql, job_config=dry_config, location="US")
    estimated = int(dry_job.total_bytes_processed or 0)
    if estimated > maximum_bytes_billed:
        raise RuntimeError(
            f"BigQuery Events-søket krever {estimated / 1024**2:.1f} MiB, over grensen på "
            f"{maximum_bytes_billed / 1024**2:.0f} MiB. Kort ned datovinduet."
        )

    config = bigquery.QueryJobConfig(
        query_parameters=parameters,
        maximum_bytes_billed=maximum_bytes_billed,
        use_query_cache=True,
    )
    job = bq.query(sql, job_config=config, location="US")
    events: list[MarketEvent] = []
    for row in job.result():
        record: dict[str, Any] = dict(row.items())
        published = record.get("published_at")
        url = str(record.get("url") or "")
        actor1 = str(record.get("actor1") or "")
        actor2 = str(record.get("actor2") or "")
        location = str(record.get("location") or "")
        raw_id = str(record.get("event_id") or "")
        event_id = "gdelt-bq:" + (
            raw_id if raw_id else hashlib.sha1(f"{published}|{url}".encode("utf-8")).hexdigest()[:24]
        )
        hits = int(record.get("keyword_hits") or 0)
        coverage = hits / max(len(keywords), 1)
        mentions = int(record.get("mentions") or 0)
        sources = int(record.get("sources") or 0)
        articles = int(record.get("articles") or 0)
        tone = float(record.get("tone") or 0.0)
        goldstein = record.get("goldstein")
        volume_strength = min(1.0, (articles + sources + mentions) / 60.0)
        significance = min(1.0, 0.25 + 0.45 * coverage + 0.30 * volume_strength)
        sensitivity = min(1.0, 0.25 + 0.45 * coverage + min(abs(tone) / 20.0, 0.20))
        actors = [value for value in (actor1, actor2) if value]

        events.append(
            MarketEvent(
                event_id=event_id,
                source="gdelt_bigquery_events",
                event_date=published.date().isoformat() if published else "",
                published_at=published.isoformat() if published else None,
                timestamp_source="gdelt-bigquery:dateadded",
                timestamp_confidence=0.98 if published else None,
                title=_title_from_url(url, actor1, actor2, location),
                summary=(
                    f"Matched {hits}/{len(keywords)} terms. CAMEO "
                    f"{record.get('event_code') or '?'}; {articles} articles, "
                    f"{sources} sources, tone {tone:+.2f}."
                ),
                category=event_type or f"cameo:{record.get('event_root_code') or 'unknown'}",
                subcategory=target or str(record.get("event_base_code") or ""),
                domain=domain or "EVENT",
                country=country or str(record.get("country_code") or ""),
                location=location,
                actors=actors,
                confidence=round(min(1.0, 0.45 + 0.40 * coverage + 0.15 * volume_strength), 4),
                market_sensitivity=round(sensitivity, 4),
                significance=round(significance, 4),
                url=url,
                raw={
                    "provider": "GDELT BigQuery Events",
                    "keywords": keywords,
                    "keyword_hits": hits,
                    "event_code": record.get("event_code"),
                    "event_base_code": record.get("event_base_code"),
                    "event_root_code": record.get("event_root_code"),
                    "goldstein_scale": goldstein,
                    "mentions": mentions,
                    "sources": sources,
                    "articles": articles,
                    "tone": tone,
                },
            )
        )

    return BigQueryEventPage(
        events=events,
        warning=None if events else "BigQuery Events svarte, men fant ingen hendelser som passerte søkekravet.",
        bytes_processed=int(job.total_bytes_processed or estimated),
    )
