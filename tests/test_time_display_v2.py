from datetime import datetime, timezone

import plotly.graph_objects as go

from time_display_v2 import localize_plotly_figure_v2, oslo_chart_time, oslo_label, oslo_time


def test_oslo_display_uses_summer_time_in_august():
    value = datetime(2026, 8, 25, 17, 0, tzinfo=timezone.utc)
    local = oslo_time(value)
    assert local.hour == 19
    assert local.tzname() == "CEST"
    assert "19:00 CEST" in oslo_label(value)


def test_oslo_chart_time_is_naive_local_clock_for_plotly():
    value = "2026-08-25T17:00:00+00:00"
    local = oslo_chart_time(value)
    assert local.hour == 19
    assert local.tzinfo is None


def test_plotly_localizer_converts_trace_clock_and_axis_label_without_mutating_source_data():
    fig = go.Figure(go.Scatter(
        x=["2026-08-25T17:00:00+00:00"],
        y=[1.0],
        hovertemplate="%{x|%H:%M} UTC<extra></extra>",
    ))
    fig.update_xaxes(title_text="Tid · UTC")
    localize_plotly_figure_v2(fig)
    assert fig.data[0].x[0].hour == 19
    assert fig.data[0].x[0].tzinfo is None
    assert "norsk tid" in fig.data[0].hovertemplate
    assert fig.layout.xaxis.title.text == "Tid · norsk tid"
