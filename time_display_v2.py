from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

OSLO = ZoneInfo("Europe/Oslo")


def parse_timestamp(value) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def oslo_time(value) -> datetime:
    return parse_timestamp(value).astimezone(OSLO)


def oslo_chart_time(value) -> datetime:
    """Convert a stored timestamp into a timezone-naive Europe/Oslo clock value for Plotly."""
    return oslo_time(value).replace(tzinfo=None)


def oslo_label(value, *, include_date: bool = True) -> str:
    parsed = oslo_time(value)
    suffix = parsed.tzname() or "norsk tid"
    if include_date:
        return f"{parsed:%d.%m.%Y %H:%M} {suffix}"
    return f"{parsed:%H:%M} {suffix}"
