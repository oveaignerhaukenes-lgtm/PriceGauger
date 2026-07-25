from world_state import _asset_bias, _direction, _mood_label, _score_rate


def test_rate_score_is_bounded_and_monotonic() -> None:
    assert _score_rate(0.0, 50.0) == 0
    assert _score_rate(50.0, 50.0) == 50
    assert _score_rate(100.0, 50.0) > 50
    assert _score_rate(1_000_000.0, 50.0) <= 100


def test_world_mood_labels() -> None:
    assert _mood_label(75) == "STRONGLY RISK-OFF"
    assert _mood_label(60) == "RISK-OFF"
    assert _mood_label(50) == "MIXED"
    assert _mood_label(40) == "RISK-ON"
    assert _mood_label(20) == "STRONGLY RISK-ON"


def test_direction_uses_material_change_threshold() -> None:
    assert _direction(8) == "DETERIORATING"
    assert _direction(-8) == "IMPROVING"
    assert _direction(6) == "STABLE"


def test_asset_bias_labels() -> None:
    assert _asset_bias(70) == "BULLISH"
    assert _asset_bias(60) == "MIXED-BULLISH"
    assert _asset_bias(50) == "NEUTRAL"
    assert _asset_bias(40) == "MIXED-BEARISH"
    assert _asset_bias(30) == "BEARISH"
