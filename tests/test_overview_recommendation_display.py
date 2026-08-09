from overview_recommendation_display import recommendation_action


def test_directional_signals_are_visible_for_observation():
    assert recommendation_action("LONG_BIAS") == "LONG"
    assert recommendation_action("SHORT_BIAS") == "SHORT"
    assert recommendation_action("NEUTRAL") == "HOLD"


def test_uncertain_non_directional_states_remain_no_trade():
    assert recommendation_action("CONFLICTED") == "NO-TRADE"
    assert recommendation_action("INSUFFICIENT_DATA") == "NO-TRADE"
    assert recommendation_action("STALE") == "NO-TRADE"
    assert recommendation_action("UNKNOWN") == "NO-TRADE"
