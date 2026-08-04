from datetime import datetime, timezone

import pandas as pd

from market_data import MarketResult
from technical_state_runtime import build_technical_market_states


def _frame() -> pd.DataFrame:
    close = [100.0 + index * 0.2 for index in range(120)]
    return pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-08-04T10:00:00Z", periods=120, freq="5min"),
            "open": close,
            "high": [value + 0.15 for value in close],
            "low": [value - 0.15 for value in close],
            "close": close,
            "volume": [1000 + index for index in range(120)],
        }
    )


def test_runtime_builds_market_state_from_three_timeframes():
    calls = []

    def fetcher(request):
        calls.append(request.interval)
        return MarketResult(_frame(), "Saxo OpenAPI")

    states, errors = build_technical_market_states(
        ["Brent"], fetcher=fetcher, now=datetime(2026, 8, 4, 20, 0, tzinfo=timezone.utc)
    )

    assert errors == {}
    assert calls == ["5min", "30min", "1h"]
    assert states["Brent"].price is not None
    assert states["Brent"].direction_score > 0
    assert states["Brent"].component.provider == "Saxo OpenAPI"
    assert states["Brent"].component.freshness == "FRESH"


def test_runtime_isolates_market_failures():
    def fetcher(request):
        if request.asset_name == "Gold":
            raise RuntimeError("no chart entitlement")
        return MarketResult(_frame(), "Saxo OpenAPI")

    states, errors = build_technical_market_states(
        ["Brent", "Gold"], fetcher=fetcher, now=datetime(2026, 8, 4, 20, 0, tzinfo=timezone.utc)
    )

    assert "Brent" in states
    assert errors == {"Gold": "no chart entitlement"}
