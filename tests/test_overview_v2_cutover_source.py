from pathlib import Path


def test_overview_market_surface_does_not_import_legacy_forecast_stack():
    source = Path("pages/0_Oversikt.py").read_text(encoding="utf-8")

    assert "from overview_v2_cards import render_v2_overview_market_cards" in source
    assert "from forecast_timeline import" not in source
    assert "from forecast_error_track import" not in source
    assert "from forecast_horizon_selector import" not in source
    assert "load_overview_markets" not in source
    assert "render_forecast_timeline_svg" not in source


def test_overview_non_card_semantic_surface_is_canonical_context_v2():
    source = Path("pages/0_Oversikt.py").read_text(encoding="utf-8")

    assert "load_context_overview_v2" in source
    assert "Semantisk kontekst · v2" in source
    assert "Context evidence / provenance" in source
    assert "load_overview()" not in source
    assert "build_overview_summary" not in source
    assert "Siste markedsflytter" not in source
    assert "information_state" not in source
