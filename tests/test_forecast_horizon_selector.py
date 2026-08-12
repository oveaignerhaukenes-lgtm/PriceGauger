from __future__ import annotations

from forecast_horizon_selector import (
    FORECAST_HORIZON_OPTIONS,
    apply_horizon_query,
    horizon_from_token,
    horizon_session_key,
    render_horizon_selector_html,
    selected_horizons_from_session,
)


def test_selector_exposes_all_eight_horizons_with_four_hour_default_active():
    markup = render_horizon_selector_html("Gold", 4.0)

    assert len(FORECAST_HORIZON_OPTIONS) == 8
    for label in ("5m", "15m", "30m", "1t", "4t", "12t", "24t", "7d"):
        assert f">{label}</a>" in markup
    assert markup.count("pg-horizon-btn") == 8
    assert 'pg-horizon-btn is-active' in markup
    assert "forecast_market=Gold" in markup
    assert "forecast_horizon=4h" in markup


def test_query_selection_is_scoped_to_one_market_and_survives_session_mapping():
    state = {horizon_session_key("Silver"): 4.0}

    assert apply_horizon_query(state, market="Gold", token="15m") is True
    selected = selected_horizons_from_session(state)

    assert selected == {"Silver": 4.0, "Gold": 0.25}
    assert horizon_from_token("7d") == 168.0


def test_invalid_query_does_not_mutate_session_state():
    state = {horizon_session_key("Gold"): 4.0}

    assert apply_horizon_query(state, market="Gold", token="2h") is False
    assert state == {horizon_session_key("Gold"): 4.0}
