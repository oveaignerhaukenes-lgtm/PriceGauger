from pathlib import Path


def test_overview_visibility_is_separate_from_collection():
    source = Path("overview_v2_cards.py").read_text(encoding="utf-8")
    assert "list_subscribed_sources_v2" in source
    assert "Markeder på Oversikt" in source
    assert "COLLECTING DATA" in source
    assert "Visning er separat fra canonical collection subscription" in source


def test_new_subscribed_market_can_surface_before_workspace():
    source = Path("overview_v2_cards.py").read_text(encoding="utf-8")
    assert "set(subscribed) | set(baselines)" in source
    assert "Canonical v2 subscription er aktiv" in source


def test_brent_identity_color_is_visible_on_dark_surface():
    source = Path("overview_visuals.py").read_text(encoding="utf-8")
    assert '"Brent": "#171717"' not in source
    assert '"Brent": "#d6a04a"' in source
