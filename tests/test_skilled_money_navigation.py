from pathlib import Path

from navigation_config import PAGE_GROUPS


def test_skilled_money_is_an_analysis_page() -> None:
    pages = PAGE_GROUPS["Analyse"]
    skilled = [page for page in pages if page.get("url_path") == "Skilled_Money"]
    assert len(skilled) == 1
    assert skilled[0]["page"] == "pages/10_Skilled_Money.py"
    assert Path(skilled[0]["page"]).is_file()
