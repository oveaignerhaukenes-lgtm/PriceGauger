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


def localize_plotly_figure_v2(fig) -> None:
    """Mutate a Plotly figure for Norwegian wall-clock presentation only.

    Stored timestamps remain UTC. Trace x-values are converted at the final UI
    boundary so analysis, resampling and database contracts stay timezone-neutral.
    """
    for trace in getattr(fig, "data", ()):
        values = getattr(trace, "x", None)
        if values is not None:
            converted = []
            for value in values:
                try:
                    converted.append(oslo_chart_time(value))
                except (TypeError, ValueError):
                    converted.append(value)
            trace.x = tuple(converted)
        hover = getattr(trace, "hovertemplate", None)
        if isinstance(hover, str) and "UTC" in hover:
            trace.hovertemplate = hover.replace("UTC", "norsk tid")

    layout = getattr(fig, "layout", None)
    if layout is None:
        return
    for key in layout:
        if not str(key).startswith("xaxis"):
            continue
        axis = layout[key]
        title = getattr(getattr(axis, "title", None), "text", None)
        if title == "Tid · UTC":
            axis.title.text = "Tid · norsk tid"
