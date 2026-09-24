from tradingdesk_ui.charts.lightweight.simple_live_v2 import _payload_key


def test_refresh_key_tracks_closed_and_forming_candle_changes():
    payload = {
        "chart_id": "Gold", "signature": "gold|5m",
        "candles": [{"time": 1, "close": 100}],
        "forming_candle": {"time": 2, "close": 101, "updated_at": "a"},
    }
    original = _payload_key("pg-simple-refresh", payload)
    assert original == _payload_key("pg-simple-refresh", dict(payload))
    assert original != _payload_key("pg-simple-refresh", {
        **payload, "forming_candle": {**payload["forming_candle"], "close": 102},
    })
    assert original != _payload_key("pg-simple-refresh", {
        **payload, "candles": [{"time": 1, "close": 102}],
    })


def test_chart_key_does_not_change_with_market_data():
    identity = {"key": "tradingdesk:Gold", "signature": "gold|5m"}
    assert _payload_key("pg-simple-chart", identity) == _payload_key("pg-simple-chart", dict(identity))
    assert _payload_key("pg-simple-chart", identity) != _payload_key(
        "pg-simple-chart", {**identity, "signature": "gold|15m"},
    )
