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
    """Return compact local wall-clock text.

    TradingDesk is already a Norwegian-local UI, so repeating CEST/CET/"norsk tid"
    on every timestamp adds noise without adding information.
    """
    parsed = oslo_time(value)
    if include_date:
        return f"{parsed:%d.%m.%Y %H:%M}"
    return f"{parsed:%H:%M}"


def _local_plotly_x(value):
    if value is None:
        return value
    try:
        return oslo_chart_time(value)
    except (TypeError, ValueError):
        return value


def localize_plotly_figure_v2(fig) -> None:
    """Mutate a Plotly figure for Norwegian wall-clock presentation only.

    Stored timestamps remain UTC. Trace x-values plus time-anchored layout shapes
    and annotations are converted at the final UI boundary so linked analytical
    overlays keep exact alignment while the displayed clock is local.
    """
    for trace in getattr(fig, "data", ()):
        values = getattr(trace, "x", None)
        if values is not None:
            trace.x = tuple(_local_plotly_x(value) for value in values)
        hover = getattr(trace, "hovertemplate", None)
        if isinstance(hover, str):
            trace.hovertemplate = (
                hover.replace(" UTC", "")
                .replace("UTC", "")
                .replace(" norsk tid", "")
                .replace("norsk tid", "")
            )

    layout = getattr(fig, "layout", None)
    if layout is None:
        return

    for shape in tuple(getattr(layout, "shapes", ()) or ()):
        xref = str(getattr(shape, "xref", "") or "")
        if xref.startswith("x"):
            if getattr(shape, "x0", None) is not None:
                shape.x0 = _local_plotly_x(shape.x0)
            if getattr(shape, "x1", None) is not None:
                shape.x1 = _local_plotly_x(shape.x1)

    for annotation in tuple(getattr(layout, "annotations", ()) or ()):
        xref = str(getattr(annotation, "xref", "") or "")
        if xref.startswith("x") and getattr(annotation, "x", None) is not None:
            annotation.x = _local_plotly_x(annotation.x)

    for key in layout:
        if not str(key).startswith("xaxis"):
            continue
        axis = layout[key]
        title = getattr(getattr(axis, "title", None), "text", None)
        if title in {"Tid · UTC", "Tid · norsk tid"}:
            axis.title.text = "Tid"
