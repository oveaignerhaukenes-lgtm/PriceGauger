from navigation_config import PAGE_GROUPS


def test_operational_navigation_groups_are_explicit() -> None:
    assert list(PAGE_GROUPS) == [
        "",
        "Oppgaver",
        "Resultater",
        "Tilkoblinger og drift",
        "Utviklerverktøy",
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


def test_legacy_search_is_not_in_the_operational_groups() -> None:
    operational = {
        page["title"]
        for group in ("", "Oppgaver", "Resultater", "Tilkoblinger og drift")
        for page in PAGE_GROUPS[group]
    }
    assert "Historisk hendelsessøk (legacy)" not in operational
    assert PAGE_GROUPS["Utviklerverktøy"][0]["title"] == "Historisk hendelsessøk (legacy)"
