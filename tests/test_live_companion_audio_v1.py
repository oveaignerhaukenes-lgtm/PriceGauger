from live_companion_audio_v1 import GOLD_ENABLED_KEY, SILVER_ENABLED_KEY, _MARKET_TOGGLE_KEYS


def test_initial_voice_markets_are_gold_and_silver_only():
    assert _MARKET_TOGGLE_KEYS == {
        "Gold": GOLD_ENABLED_KEY,
        "Silver": SILVER_ENABLED_KEY,
    }
