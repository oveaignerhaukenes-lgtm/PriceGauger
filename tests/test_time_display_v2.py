from datetime import datetime, timezone

import plotly.graph_objects as go

from time_display_v2 import localize_plotly_figure_v2, oslo_chart_time, oslo_label, oslo_time


def test_oslo_display_uses_summer_time_in_august():
    value = datetime(2026, 8, 25, 17, 0, tzinfo=timezone.utc)
    local = oslo_time(value)
    assert local.hour == 19
    assert local.tzname() == "CEST"
    assert oslo_label(value) == "25.08.2026 19:00"
    assert oslo_label(value, include_date=False) == "19:00"


def test_oslo_chart_time_is_naive_local_clock_for_plotly():
    value = "2026-08-25T17:00:00+00:00"
    local = oslo_chart_time(value)
    assert local.hour == 19
    assert local.tzinfo is None


def test_plotly_localizer_converts_trace_clock_and_strips_redundant_timezone_copy():
    fig = go.Figure(go.Scatter(
        x=["2026-08-25T17:00:00+00:00"],
        y=[1.0],
        hovertemplate="%{x|%H:%M} UTC<extra></extra>",
    ))
    fig.update_xaxes(title_text="Tid · UTC")
    localize_plotly_figure_v2(fig)
    assert fig.data[0].x[0].hour == 19
    assert fig.data[0].x[0].tzinfo is None
    assert "UTC" not in fig.data[0].hovertemplate
    assert "norsk tid" not in fig.data[0].hovertemplate
    assert fig.layout.xaxis.title.text == "Tid"


def test_plotly_localizer_keeps_epoch_shapes_and_annotations_aligned_with_trace_clock():
    source = datetime(2026, 8, 25, 17, 0, tzinfo=timezone.utc)
    fig = go.Figure(go.Scatter(x=[source], y=[1.0]))
    fig.add_shape(type="line", x0=source, x1=source, y0=0, y1=1, xref="x", yref="paper")
    fig.add_annotation(x=source, y=1.0, xref="x", yref="paper", text="MTF")

    localize_plotly_figure_v2(fig)

    assert fig.data[0].x[0].hour == 19
    assert fig.layout.shapes[0].x0.hour == 19
    assert fig.layout.shapes[0].x1.hour == 19
    assert fig.layout.annotations[0].x.hour == 19
    assert fig.layout.shapes[0].x0.tzinfo is None
    assert fig.layout.annotations[0].x.tzinfo is None
