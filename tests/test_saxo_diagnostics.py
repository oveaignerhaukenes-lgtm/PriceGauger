from __future__ import annotations

import pandas as pd

from saxo_diagnostics import diagnose_chart, diagnose_info_price


def test_info_price_reports_no_access_before_delay_unknown() -> None:
    result = diagnose_info_price({"PriceInfo": {"PriceStatus": "NoAccess"}, "Quote": {}})

    assert result.status == "NO_ACCESS"
    assert result.has_access is False
    assert result.has_price is False


def test_info_price_reports_realtime_quote() -> None:
    result = diagnose_info_price(
        {
            "PriceInfo": {"PriceStatus": "Tradable"},
            "Quote": {"Bid": 80.0, "Ask": 80.2, "DelayedByMinutes": 0},
        }
    )

    assert result.status == "REALTIME"
    assert result.mid == 80.1
    assert result.delay_minutes == 0


def test_info_price_reports_delayed_quote() -> None:
    result = diagnose_info_price(
        {
            "PriceInfo": {"PriceStatus": "Tradable"},
            "Quote": {"Bid": 80.0, "Ask": 80.2, "DelayedByMinutes": 15},
        }
    )

    assert result.status == "DELAYED_15MIN"
    assert result.has_price is True


def test_chart_diagnostic_reports_last_bar_age() -> None:
    frame = pd.DataFrame(
        {
            "timestamp": ["2026-07-24T21:50:00Z", "2026-07-24T21:55:00Z"],
            "close": [80.0, 80.1],
        }
    )

    result = diagnose_chart(frame, now=pd.Timestamp("2026-07-24T22:00:00Z"))

    assert result.status == "CHART_AVAILABLE"
    assert result.bars == 2
    assert result.last_close == 80.1
    assert result.age_minutes == 5.0


def test_chart_diagnostic_handles_empty_frame() -> None:
    result = diagnose_chart(pd.DataFrame())

    assert result.status == "NO_BARS"
    assert result.bars == 0
