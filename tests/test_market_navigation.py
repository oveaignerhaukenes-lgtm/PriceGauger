from market_navigation import market_detail_href


def test_market_detail_href_routes_through_app_shell():
    assert market_detail_href("Gold") == "/?open_market=Gold"
    assert market_detail_href("Natural Gas") == "/?open_market=Natural%20Gas"
