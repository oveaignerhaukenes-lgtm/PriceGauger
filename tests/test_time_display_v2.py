from datetime import datetime, timezone

from time_display_v2 import oslo_chart_time, oslo_label, oslo_time


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
