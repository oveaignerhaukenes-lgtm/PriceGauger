from market_navigation import market_detail_href


def test_market_detail_href_routes_to_selected_market():
    assert market_detail_href("Gold") == "/Forecast_Learning?market=Gold"
    assert market_detail_href("Natural Gas") == "/Forecast_Learning?market=Natural%20Gas"
