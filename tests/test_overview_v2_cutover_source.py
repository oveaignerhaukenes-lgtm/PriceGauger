from pathlib import Path


def test_overview_market_surface_does_not_import_legacy_forecast_stack():
    source = Path("pages/0_Oversikt.py").read_text(encoding="utf-8")

    assert "from overview_v2_cards import render_v2_overview_market_cards" in source
    assert "from forecast_timeline import" not in source
    assert "from forecast_error_track import" not in source
    assert "from forecast_horizon_selector import" not in source
    assert "load_overview_markets" not in source
    assert "render_forecast_timeline_svg" not in source


def test_overview_keeps_non_card_event_and_summary_surfaces_intact():
    source = Path("pages/0_Oversikt.py").read_text(encoding="utf-8")

    assert "build_overview_summary" in source
    assert "Siste markedsflytter" in source
    assert "Siste hendelser" in source
    assert "load_overview()" in source
