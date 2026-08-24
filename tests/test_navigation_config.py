from navigation_config import PAGE_GROUPS


def test_operational_navigation_groups_are_explicit() -> None:
    assert list(PAGE_GROUPS) == [
        "",
        "Oppgaver",
        "Resultater",
        "Tilkoblinger og drift",
    ]


def test_overview_is_the_only_default_page() -> None:
    defaults = [
        page
        for pages in PAGE_GROUPS.values()
        for page in pages
        if page.get("default")
    ]
    assert defaults == [PAGE_GROUPS[""][0]]
    assert defaults[0]["title"] == "Oversikt"


def test_tradingdesk_is_a_prominent_top_level_operational_page() -> None:
    assert [page["title"] for page in PAGE_GROUPS[""]] == ["Oversikt", "TradingDesk"]
    trading_desk = PAGE_GROUPS[""][1]
    assert trading_desk["page"] == "pages/0_TradingDesk.py"
    assert trading_desk["url_path"] == "TradingDesk"
    assert not trading_desk.get("default", False)


def test_saxo_callback_route_is_preserved() -> None:
    pages = [page for group in PAGE_GROUPS.values() for page in group]
    saxo = next(page for page in pages if page["title"] == "Saxo")
    assert saxo["url_path"] == "Saxo_OpenAPI"


def test_retired_historical_event_lab_is_absent_from_navigation() -> None:
    pages = [page for group in PAGE_GROUPS.values() for page in group]
    assert all(page["page"] != "pages/1_Historical_Event_Lab.py" for page in pages)
    assert all(page["title"] != "Historisk hendelsessøk (legacy)" for page in pages)
