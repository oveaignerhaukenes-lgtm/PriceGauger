from navigation_config import PAGE_GROUPS


def _all_pages():
    return [page for group in PAGE_GROUPS.values() for page in group]


def test_navigation_groups_separate_product_from_developer_surfaces() -> None:
    assert list(PAGE_GROUPS) == [
        "",
        "Analyse",
        "Tilkoblinger og handel",
        "Utviklerverktøy",
        "Utviklerverktøy · Legacy",
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


def test_product_analysis_menu_uses_canonical_v2_technical_surface() -> None:
    analysis = PAGE_GROUPS["Analyse"]
    technical = next(page for page in analysis if page["title"] == "Teknisk analyse")
    assert technical["page"] == "pages/9_V2_Technical.py"
    assert all(page["page"] != "pages/2_Direct_Technical.py" for page in analysis)


def test_legacy_surfaces_are_visibly_isolated_from_product_groups() -> None:
    product_groups = ("", "Analyse", "Tilkoblinger og handel")
    product_pages = [page for group in product_groups for page in PAGE_GROUPS[group]]
    legacy_pages = PAGE_GROUPS["Utviklerverktøy · Legacy"]

    retired_paths = {
        "pages/1_Kjerneflyt.py",
        "pages/2_Direct_Technical.py",
        "pages/5_AI_Market_Assessment.py",
        "pages/2_Signalaggregat.py",
        "pages/Market_State.py",
        "pages/Signal_History.py",
        "pages/7_Forecast_Learning.py",
    }
    assert retired_paths.isdisjoint({page["page"] for page in product_pages})
    assert retired_paths == {page["page"] for page in legacy_pages}
    assert all(page["title"].startswith("Legacy · ") for page in legacy_pages)


def test_active_diagnostics_remain_available_under_developer_tools() -> None:
    developer_paths = {page["page"] for page in PAGE_GROUPS["Utviklerverktøy"]}
    assert developer_paths == {
        "pages/Worker_Status.py",
        "pages/99_Runtime_Diagnostics.py",
        "pages/7_Benchmark.py",
    }


def test_saxo_callback_route_is_preserved() -> None:
    saxo = next(page for page in _all_pages() if page["title"] == "Saxo")
    assert saxo["url_path"] == "Saxo_OpenAPI"


def test_retired_historical_event_lab_is_absent_from_navigation() -> None:
    pages = _all_pages()
    assert all(page["page"] != "pages/1_Historical_Event_Lab.py" for page in pages)
    assert all(page["title"] != "Historisk hendelsessøk (legacy)" for page in pages)
