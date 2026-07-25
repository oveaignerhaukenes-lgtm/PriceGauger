from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
import re
from typing import Any
from urllib.parse import unquote, urlparse

from google.cloud import bigquery

from event_models import MarketEvent

GDELT_GKG_TABLE = "gdelt-bq.gdeltv2.gkg_partitioned"
MAX_BYTES_BILLED = 2 * 1024**3
_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{2,}")
_STOPWORDS = {
    "after", "against", "amid", "and", "attack", "breaking", "from", "into",
    "near", "over", "reported", "reports", "says", "that", "the", "their",
    "this", "with", "will",
}


@dataclass(frozen=True, slots=True)
class BigQueryEventPage:
    events: list[MarketEvent]
    source: str = "GDELT BigQuery"
    warning: str | None = None
    bytes_processed: int = 0


def _keywords(search: str, country: str, *, limit: int = 8) -> list[str]:
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


def _title_from_url(url: str, themes: str) -> str:
    path = unquote(urlparse(url).path).strip("/")
    if path:
        candidate = path.rsplit("/", 1)[-1].replace("-", " ").replace("_", " ")
        candidate = " ".join(candidate.split())
        if len(candidate) >= 8:
            return candidate[:240]
    visible_themes = [item.split(",", 1)[0] for item in (themes or "").split(";") if item]
    return " · ".join(visible_themes[:5])[:240] or "GDELT historical document"


def _first_location(value: str) -> tuple[str, str]:
    first = next((item for item in (value or "").split(";") if item), "")
    fields = first.split("#")
    location = fields[1].strip() if len(fields) > 1 else ""
    country = fields[2].strip() if len(fields) > 2 else ""
    return location, country


def _actors(persons: str, organisations: str) -> list[str]:
    values: list[str] = []
    for source in (persons, organisations):
        for item in (source or "").split(";"):
            name = item.strip()
            if name and name not in values:
                values.append(name)
            if len(values) >= 12:
                return values
    return values


def _query() -> str:
    return f"""
    WITH source AS (
      SELECT
        SAFE.PARSE_TIMESTAMP('%Y%m%d%H%M%S', CAST(DATE AS STRING)) AS published_at,
        DocumentIdentifier AS url,
        COALESCE(V2Themes, Themes, '') AS themes,
        COALESCE(V2Locations, Locations, '') AS locations,
        COALESCE(V2Persons, Persons, '') AS persons,
        COALESCE(V2Organizations, Organizations, '') AS organisations,
        SAFE_CAST(SPLIT(V2Tone, ',')[SAFE_OFFSET(0)] AS FLOAT64) AS tone,
        LOWER(CONCAT(
          COALESCE(DocumentIdentifier, ''), ' ',
          COALESCE(V2Themes, Themes, ''), ' ',
          COALESCE(V2Locations, Locations, ''), ' ',
          COALESCE(V2Persons, Persons, ''), ' ',
          COALESCE(V2Organizations, Organizations, '')
        )) AS searchable
      FROM `{GDELT_GKG_TABLE}`
      WHERE _PARTITIONDATE BETWEEN @start_date AND @end_date
    )
    SELECT
      published_at, url, themes, locations, persons, organisations, tone,
      (SELECT COUNTIF(STRPOS(searchable, keyword) > 0) FROM UNNEST(@keywords) keyword) AS keyword_hits
    FROM source
    WHERE (SELECT COUNTIF(STRPOS(searchable, keyword) > 0) FROM UNNEST(@keywords) keyword) >= @minimum_hits
    QUALIFY ROW_NUMBER() OVER (PARTITION BY url ORDER BY published_at ASC) = 1
    ORDER BY keyword_hits DESC, published_at DESC
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
    minimum_hits = 1 if len(keywords) <= 2 else 2
    parameters = [
        bigquery.ScalarQueryParameter("start_date", "DATE", start),
        bigquery.ScalarQueryParameter("end_date", "DATE", end),
        bigquery.ArrayQueryParameter("keywords", "STRING", keywords),
        bigquery.ScalarQueryParameter("minimum_hits", "INT64", minimum_hits),
        bigquery.ScalarQueryParameter("row_limit", "INT64", max(5, min(int(limit), 250))),
    ]
    sql = _query()
    bq = client or bigquery.Client()
    dry_config = bigquery.QueryJobConfig(query_parameters=parameters, dry_run=True, use_query_cache=False)
    dry_job = bq.query(sql, job_config=dry_config, location="US")
    estimated = int(dry_job.total_bytes_processed or 0)
    if estimated > maximum_bytes_billed:
        raise RuntimeError(
            f"BigQuery-søket krever {estimated / 1024**3:.2f} GiB, over grensen på "
            f"{maximum_bytes_billed / 1024**3:.2f} GiB"
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
        themes = str(record.get("themes") or "")
        location, detected_country = _first_location(str(record.get("locations") or ""))
        event_id = "gdelt-bq:" + hashlib.sha1(f"{published}|{url}".encode("utf-8")).hexdigest()[:24]
        hits = int(record.get("keyword_hits") or 0)
        coverage = hits / max(len(keywords), 1)
        tone = record.get("tone")
        significance = min(1.0, 0.35 + 0.65 * coverage)
        sensitivity = min(1.0, 0.30 + 0.50 * coverage + min(abs(float(tone or 0.0)) / 20.0, 0.20))
        events.append(
            MarketEvent(
                event_id=event_id,
                source="gdelt_bigquery_gkg",
                event_date=published.date().isoformat() if published else "",
                published_at=published.isoformat() if published else None,
                timestamp_source="gdelt-bigquery:gkg-date",
                timestamp_confidence=0.98 if published else None,
                title=_title_from_url(url, themes),
                summary=f"Matched {hits}/{len(keywords)} terms: {', '.join(keywords)}. Themes: {themes[:700]}",
                category=event_type or "historical_news",
                subcategory=target or "",
                domain=domain or "INFORMATION",
                country=country or detected_country,
                location=location,
                actors=_actors(str(record.get("persons") or ""), str(record.get("organisations") or "")),
                confidence=round(min(1.0, 0.50 + 0.50 * coverage), 4),
                market_sensitivity=round(sensitivity, 4),
                significance=round(significance, 4),
                url=url,
                raw={
                    "provider": "GDELT BigQuery",
                    "keywords": keywords,
                    "keyword_hits": hits,
                    "themes": themes,
                    "tone": tone,
                },
            )
        )

    return BigQueryEventPage(
        events=events,
        warning=None if events else "BigQuery svarte, men fant ingen dokumenter som passerte søkekravet.",
        bytes_processed=int(job.total_bytes_processed or estimated),
    )
