from pathlib import Path


def test_saxo_callback_route_matches_registered_redirect() -> None:
    page = Path("pages/1_Saxo_OpenAPI.py")

    assert page.is_file()
    source = page.read_text(encoding="utf-8")
    assert "handle_saxo_oauth_callback()" in source
    assert not Path("pages/1_Saxo.py").exists()


def test_overview_links_to_saxo_callback_page() -> None:
    source = Path("pages/0_Oversikt.py").read_text(encoding="utf-8")

    assert 'st.page_link("pages/1_Saxo_OpenAPI.py"' in source
