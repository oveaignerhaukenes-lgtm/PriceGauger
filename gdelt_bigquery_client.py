from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from hashlib import sha1
from typing import Any
from urllib.parse import urlparse

from event_models import MarketEvent
from gdelt_types import GdeltError, GdeltPage

DEFAULT_MAX_BYTES_BILLED = 5 * 1024**3
_STOPWORDS = {
    "about",
    "after",
    "against",
    "before",
    "during",
    "from",
    "into",
    "news",
    "over",
    "that",
    "the",
    "this",
    "with",
}


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value[:10])
    except ValueError as exc:
        raise GdeltError(f"Ugyldig dato: {value!r}", stage="spørring") from exc


def _search_pattern(search: str) -> str:
    terms: list[str] = []
    for token in re.findall(r"[A-Za-z0-9_-]+", search.upper()):
        if len(token) < 3 or token.lower() in _STOPWORDS or token in terms:
            continue
        terms.append(token)
        if len(terms) == 8:
            break
    return "|".join(re.escape(term) for term in terms)


def _published_at(value: Any) -> str | None:
    cleaned = str(value or "").strip()
    if not cleaned:
        return None
    try:
        parsed = datetime.strptime(cleaned, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return parsed.isoformat()


def _row_value(row: Any, name: str, default: Any = None) -> Any:
    try:
        return row[name]
    except (KeyError, TypeError):
        return getattr(row, name, default)


def _event_from_row(row: Any) -> MarketEvent:
    raw = dict(row.items()) if hasattr(row, "items") else dict(row)
    url = str(_row_value(row, "SOURCEURL", "") or "")
    event_id_value = str(_row_value(row, "GLOBALEVENTID", "") or "")
    identity = f"{event_id_value}|{url}"
    event_id = "gdelt-bq:" + sha1(identity.encode("utf-8")).hexdigest()[:20]
    actor1 = str(_row_value(row, "Actor1Name", "") or "").strip()
    actor2 = str(_row_value(row, "Actor2Name", "") or "").strip()
    actors = [value for value in (actor1, actor2) if value]
    event_code = str(_row_value(row, "EventCode", "") or "")
    root_code = str(_row_value(row, "EventRootCode", "") or "")
    location = str(_row_value(row, "ActionGeo_FullName", "") or "")
    country = str(_row_value(row, "ActionGeo_CountryCode", "") or "")
    sql_date = str(_row_value(row, "SQLDATE", "") or "")
    event_date = f"{sql_date[:4]}-{sql_date[4:6]}-{sql_date[6:8]}" if len(sql_date) == 8 else ""
    title_parts = [" ↔ ".join(actors) if actors else "GDELT event"]
    if event_code:
        title_parts.append(f"CAMEO {event_code}")
    title = " · ".join(title_parts)
    mentions = _row_value(row, "NumMentions")
    goldstein = _row_value(row, "GoldsteinScale")
    try:
        significance = float(mentions) if mentions is not None else None
    except (TypeError, ValueError):
        significance = None
    try:
        market_sensitivity = abs(float(goldstein)) if goldstein is not None else None
    except (TypeError, ValueError):
        market_sensitivity = None
    published_at = _published_at(_row_value(row, "DATEADDED"))
    return MarketEvent(
        event_id=event_id,
        source="gdelt_bigquery_v2",
        event_date=event_date,
        title=title,
        summary=title,
        category="cameo_event",
        subcategory=root_code,
        domain=urlparse(url).netloc,
        country=country,
        location=location,
        actors=actors,
        confidence=None,
        market_sensitivity=market_sensitivity,
        significance=significance,
        url=url,
        raw=raw,
        published_at=published_at,
        timestamp_source="gdelt:DATEADDED" if published_at else None,
        timestamp_confidence=0.80 if published_at else None,
    )


@dataclass(slots=True)
class BigQueryGdeltClient:
    project: str = "pricegauger"
    maximum_bytes_billed: int = DEFAULT_MAX_BYTES_BILLED
    client: Any | None = None
    bigquery_module: Any | None = None

    def _dependencies(self) -> tuple[Any, Any]:
        module = self.bigquery_module
        client = self.client
        if module is None:
            try:
                from google.cloud import bigquery as module
            except ImportError as exc:
                raise GdeltError(
                    "google-cloud-bigquery er ikke installert.",
                    stage="konfigurasjon",
                ) from exc
        if client is None:
            try:
                client = module.Client(project=self.project)
            except Exception as exc:
                raise GdeltError(
                    "Kunne ikke opprette BigQuery-klient. Kontroller Application Default Credentials.",
                    stage="autentisering",
                ) from exc
        return module, client

    def list_events(
        self,
        *,
        date_start: str,
        date_end: str,
        search: str = "",
        country: str = "",
        category: str = "",
        domain: str = "",
        event_family: str = "",
        confidence_profile: str = "precise",
        sort: str = "significance",
        limit: int = 50,
        cursor: str | None = None,
    ) -> GdeltPage:
        del category, domain, event_family, confidence_profile, sort, cursor
        module, client = self._dependencies()
        start_date = _parse_date(date_start)
        end_date = _parse_date(date_end)
        if end_date < start_date:
            raise GdeltError("Sluttdato er før startdato.", stage="spørring")

        query = """
        SELECT
            GLOBALEVENTID,
            SQLDATE,
            Actor1Name,
            Actor2Name,
            EventCode,
            EventRootCode,
            GoldsteinScale,
            NumMentions,
            ActionGeo_CountryCode,
            ActionGeo_FullName,
            SOURCEURL,
            DATEADDED
        FROM `gdelt-bq.gdeltv2.events_partitioned`
        WHERE
            _PARTITIONDATE BETWEEN @start_date AND @end_date
            AND SQLDATE BETWEEN
                CAST(FORMAT_DATE('%Y%m%d', @start_date) AS INT64)
                AND CAST(FORMAT_DATE('%Y%m%d', @end_date) AS INT64)
            AND (
                @country = ''
                OR UPPER(COALESCE(Actor1Name, '')) LIKE CONCAT('%', UPPER(@country), '%')
                OR UPPER(COALESCE(Actor2Name, '')) LIKE CONCAT('%', UPPER(@country), '%')
                OR UPPER(COALESCE(ActionGeo_FullName, '')) LIKE CONCAT('%', UPPER(@country), '%')
            )
            AND (
                @search_pattern = ''
                OR REGEXP_CONTAINS(
                    UPPER(CONCAT(
                        COALESCE(Actor1Name, ''), ' ',
                        COALESCE(Actor2Name, ''), ' ',
                        COALESCE(ActionGeo_FullName, ''), ' ',
                        COALESCE(SOURCEURL, '')
                    )),
                    @search_pattern
                )
            )
        ORDER BY NumMentions DESC, SQLDATE DESC
        LIMIT @limit
        """
        parameters = [
            module.ScalarQueryParameter("start_date", "DATE", start_date),
            module.ScalarQueryParameter("end_date", "DATE", end_date),
            module.ScalarQueryParameter("country", "STRING", country.strip()),
            module.ScalarQueryParameter("search_pattern", "STRING", _search_pattern(search)),
            module.ScalarQueryParameter("limit", "INT64", max(1, min(int(limit), 250))),
        ]
        dry_config = module.QueryJobConfig(
            query_parameters=parameters,
            dry_run=True,
            use_query_cache=False,
        )
        try:
            dry_job = client.query(query, job_config=dry_config, location="US")
            estimated = int(dry_job.total_bytes_processed or 0)
            if estimated > self.maximum_bytes_billed:
                raise GdeltError(
                    "BigQuery-søket ble avvist fordi estimert datamengde overstiger kostnadsgrensen.",
                    stage="kostnadsgrense",
                )
            run_config = module.QueryJobConfig(
                query_parameters=parameters,
                maximum_bytes_billed=self.maximum_bytes_billed,
                use_query_cache=True,
            )
            rows = client.query(query, job_config=run_config, location="US").result()
        except GdeltError:
            raise
        except Exception as exc:
            raise GdeltError("BigQuery-spørringen mislyktes.", stage="BigQuery") from exc

        events: list[MarketEvent] = []
        seen_urls: set[str] = set()
        for row in rows:
            event = _event_from_row(row)
            key = event.url.strip().lower() or event.event_id
            if key in seen_urls:
                continue
            seen_urls.add(key)
            events.append(event)
        warning = None if events else "GDELT BigQuery returnerte ingen hendelser for dette søket."
        return GdeltPage(events=events, next_cursor=None, warning=warning)
