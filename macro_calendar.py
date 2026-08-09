from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
import re
from typing import Iterable
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup


OSLO = ZoneInfo("Europe/Oslo")
NEW_YORK = ZoneInfo("America/New_York")

BLS_ICS_URL = "https://www.bls.gov/schedule/news_release/bls.ics"
BEA_SCHEDULE_URL = "https://www.bea.gov/news/schedule"
FED_MONETARY_POLICY_URL = "https://www.federalreserve.gov/monetarypolicy.htm"
EIA_PETROLEUM_SCHEDULE_URL = "https://www.eia.gov/petroleum/supply/weekly/schedule.php"
EIA_GAS_SCHEDULE_URL = "https://www.eia.gov/ngs/schedule.html"


@dataclass(frozen=True, slots=True)
class MacroEvent:
    event_id: str
    scheduled_at: datetime
    title: str
    source: str
    source_url: str
    importance: str
    markets: tuple[str, ...]
    event_type: str

    @property
    def scheduled_at_oslo(self) -> datetime:
        return self.scheduled_at.astimezone(OSLO)


@dataclass(frozen=True, slots=True)
class MacroCalendarResult:
    events: tuple[MacroEvent, ...]
    source_errors: tuple[str, ...] = ()


BLS_RULES = (
    ("consumer price index", "US_CPI", "CPI", "HIGH", ("Gold", "Silver", "DXY", "US10Y"), "https://www.bls.gov/cpi/"),
    ("producer price index", "US_PPI", "PPI", "HIGH", ("Gold", "Silver", "DXY", "US10Y"), "https://www.bls.gov/ppi/"),
    ("employment situation", "US_NFP", "Employment Situation / NFP", "HIGH", ("Gold", "Silver", "DXY", "US10Y", "Brent"), "https://www.bls.gov/news.release/empsit.htm"),
)

BEA_RULES = (
    ("personal income and outlays", "US_PCE", "Personal Income & Outlays / PCE", "HIGH", ("Gold", "Silver", "DXY", "US10Y")),
    ("gdp", "US_GDP", "GDP", "MEDIUM", ("Gold", "Silver", "DXY", "US10Y", "Brent")),
)

MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}


def _event_id(event_type: str, scheduled_at: datetime) -> str:
    return f"{event_type}:{scheduled_at.astimezone(timezone.utc).strftime('%Y%m%dT%H%MZ')}"


def _in_window(value: datetime, start: datetime, end: datetime) -> bool:
    return start <= value <= end


def _parse_ics_datetime(header: str, value: str) -> datetime | None:
    value = value.strip()
    if not value:
        return None
    tz_match = re.search(r"TZID=([^;:]+)", header, flags=re.IGNORECASE)
    tz = ZoneInfo(tz_match.group(1)) if tz_match else NEW_YORK
    for fmt in ("%Y%m%dT%H%M%S", "%Y%m%dT%H%M"):
        try:
            parsed = datetime.strptime(value.rstrip("Z"), fmt)
            if value.endswith("Z"):
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.replace(tzinfo=tz).astimezone(timezone.utc)
        except ValueError:
            continue
    return None


def _unfold_ics(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").split("\n"):
        if raw.startswith((" ", "\t")) and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    return lines


def parse_bls_ics(text: str, *, start: datetime, end: datetime) -> list[MacroEvent]:
    events: list[MacroEvent] = []
    current: dict[str, str] | None = None
    for line in _unfold_ics(text):
        if line == "BEGIN:VEVENT":
            current = {}
            continue
        if line == "END:VEVENT":
            if current is None:
                continue
            summary = current.get("SUMMARY", "")
            summary_lower = summary.lower()
            dt_key = next((key for key in current if key.startswith("DTSTART")), None)
            scheduled = _parse_ics_datetime(dt_key or "", current.get(dt_key or "", "")) if dt_key else None
            if scheduled is not None and _in_window(scheduled, start, end):
                for needle, event_type, title, importance, markets, source_url in BLS_RULES:
                    if needle in summary_lower:
                        events.append(
                            MacroEvent(
                                event_id=_event_id(event_type, scheduled),
                                scheduled_at=scheduled,
                                title=title,
                                source="BLS",
                                source_url=source_url,
                                importance=importance,
                                markets=markets,
                                event_type=event_type,
                            )
                        )
                        break
            current = None
            continue
        if current is not None and ":" in line:
            key, value = line.split(":", 1)
            current[key] = value
    return events


def _parse_us_datetime(value: str, *, year: int) -> datetime | None:
    compact = " ".join(value.replace(".", "").split())
    match = re.search(
        r"(?P<month>January|February|March|April|May|June|July|August|September|October|November|December)\s+"
        r"(?P<day>\d{1,2})\s+(?P<hour>\d{1,2}):(?P<minute>\d{2})\s*(?P<ampm>AM|PM)",
        compact,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    month = MONTHS[match.group("month").lower()]
    hour = int(match.group("hour"))
    if match.group("ampm").upper() == "PM" and hour != 12:
        hour += 12
    if match.group("ampm").upper() == "AM" and hour == 12:
        hour = 0
    local = datetime(year, month, int(match.group("day")), hour, int(match.group("minute")), tzinfo=NEW_YORK)
    return local.astimezone(timezone.utc)


def parse_bea_schedule(html: str, *, start: datetime, end: datetime) -> list[MacroEvent]:
    soup = BeautifulSoup(html, "html.parser")
    events: list[MacroEvent] = []
    years = {start.astimezone(NEW_YORK).year, end.astimezone(NEW_YORK).year}
    for row in soup.select("tr"):
        cells = row.find_all(["th", "td"])
        if len(cells) < 2:
            continue
        cell_texts = [" ".join(cell.get_text(" ", strip=True).split()) for cell in cells]
        combined = " | ".join(cell_texts)
        release_text = max(cell_texts, key=len, default="")
        release_lower = release_text.lower()
        rule = next((item for item in BEA_RULES if item[0] in release_lower), None)
        if rule is None:
            continue
        scheduled = None
        for year in sorted(years):
            scheduled = _parse_us_datetime(combined, year=year)
            if scheduled and _in_window(scheduled, start, end):
                break
            scheduled = None
        if scheduled is None:
            continue
        _, event_type, title, importance, markets = rule
        anchor = row.find("a", href=True)
        link = urljoin(BEA_SCHEDULE_URL, anchor["href"]) if anchor else BEA_SCHEDULE_URL
        events.append(
            MacroEvent(
                event_id=_event_id(event_type, scheduled),
                scheduled_at=scheduled,
                title=title,
                source="BEA",
                source_url=link,
                importance=importance,
                markets=markets,
                event_type=event_type,
            )
        )
    return events


def parse_fed_upcoming(html: str, *, start: datetime, end: datetime) -> list[MacroEvent]:
    text = " ".join(BeautifulSoup(html, "html.parser").get_text(" ", strip=True).split())
    pattern = re.compile(
        r"(?P<month>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+"
        r"(?P<days>\d{1,2}(?:-\d{1,2})?)\s+"
        r"(?P<label>FOMC Meeting|FOMC Minutes)",
        flags=re.IGNORECASE,
    )
    events: list[MacroEvent] = []
    candidate_years = range(start.astimezone(NEW_YORK).year, end.astimezone(NEW_YORK).year + 1)
    for match in pattern.finditer(text):
        month_token = match.group("month").lower().rstrip(".")
        month = MONTHS[month_token]
        day = int(match.group("days").split("-")[-1])
        label = match.group("label")
        for year in candidate_years:
            try:
                local = datetime(year, month, day, 14, 0, tzinfo=NEW_YORK)
            except ValueError:
                continue
            scheduled = local.astimezone(timezone.utc)
            if not _in_window(scheduled, start, end):
                continue
            if label.lower().endswith("minutes"):
                event_type = "FOMC_MINUTES"
                title = "FOMC Minutes"
                importance = "HIGH"
            else:
                event_type = "FOMC_DECISION"
                title = "FOMC rate decision / statement"
                importance = "CRITICAL"
            events.append(
                MacroEvent(
                    event_id=_event_id(event_type, scheduled),
                    scheduled_at=scheduled,
                    title=title,
                    source="Federal Reserve",
                    source_url=FED_MONETARY_POLICY_URL,
                    importance=importance,
                    markets=("Gold", "Silver", "DXY", "US10Y", "Brent", "Natural Gas"),
                    event_type=event_type,
                )
            )
            break
    return events


def recurring_eia_events(*, start: datetime, end: datetime) -> list[MacroEvent]:
    start_local = start.astimezone(NEW_YORK)
    cursor = start_local.date()
    end_date = end.astimezone(NEW_YORK).date()
    events: list[MacroEvent] = []
    while cursor <= end_date:
        if cursor.weekday() == 2:  # Wednesday
            local = datetime.combine(cursor, time(10, 30), tzinfo=NEW_YORK)
            scheduled = local.astimezone(timezone.utc)
            if _in_window(scheduled, start, end):
                events.append(
                    MacroEvent(
                        event_id=_event_id("EIA_WPSR", scheduled),
                        scheduled_at=scheduled,
                        title="EIA Weekly Petroleum Status Report",
                        source="EIA",
                        source_url=EIA_PETROLEUM_SCHEDULE_URL,
                        importance="HIGH",
                        markets=("Brent",),
                        event_type="EIA_WPSR",
                    )
                )
        if cursor.weekday() == 3:  # Thursday
            local = datetime.combine(cursor, time(10, 30), tzinfo=NEW_YORK)
            scheduled = local.astimezone(timezone.utc)
            if _in_window(scheduled, start, end):
                events.append(
                    MacroEvent(
                        event_id=_event_id("EIA_NG_STORAGE", scheduled),
                        scheduled_at=scheduled,
                        title="EIA Weekly Natural Gas Storage Report",
                        source="EIA",
                        source_url=EIA_GAS_SCHEDULE_URL,
                        importance="HIGH",
                        markets=("Natural Gas",),
                        event_type="EIA_NG_STORAGE",
                    )
                )
        cursor += timedelta(days=1)
    return events


def _get_text(url: str, *, timeout: float = 12.0) -> str:
    response = requests.get(url, timeout=timeout, headers={"User-Agent": "PriceGauger/0.9 macro-calendar"})
    response.raise_for_status()
    return response.text


def load_macro_calendar(
    *,
    now: datetime | None = None,
    horizon_days: int = 90,
    fetcher=_get_text,
) -> MacroCalendarResult:
    start = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    end = start + timedelta(days=max(1, int(horizon_days)))
    events: list[MacroEvent] = []
    errors: list[str] = []

    for name, url, parser in (
        ("BLS", BLS_ICS_URL, parse_bls_ics),
        ("BEA", BEA_SCHEDULE_URL, parse_bea_schedule),
        ("Federal Reserve", FED_MONETARY_POLICY_URL, parse_fed_upcoming),
    ):
        try:
            payload = fetcher(url)
            events.extend(parser(payload, start=start, end=end))
        except Exception as exc:
            errors.append(f"{name}: {exc}")

    events.extend(recurring_eia_events(start=start, end=end))

    deduped = {event.event_id: event for event in events}
    ordered = tuple(sorted(deduped.values(), key=lambda item: item.scheduled_at))
    return MacroCalendarResult(events=ordered, source_errors=tuple(errors))


def calendar_rows(events: Iterable[MacroEvent]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for event in events:
        local = event.scheduled_at_oslo
        rows.append(
            {
                "Dato": local.strftime("%d.%m.%Y"),
                "Klokkeslett": local.strftime("%H:%M"),
                "Hendelse": event.title,
                "Viktighet": event.importance,
                "Markeder": ", ".join(event.markets),
                "Kilde": event.source,
                "Lenke": event.source_url,
            }
        )
    return rows
