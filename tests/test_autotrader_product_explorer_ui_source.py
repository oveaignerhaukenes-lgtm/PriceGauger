from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_product_explorer_exposes_bounded_v2_onboarding_without_execution_path() -> None:
    explorer_source = (ROOT / "autotrader_product_explorer_ui.py").read_text(encoding="utf-8")
    onboarding_source = (ROOT / "instrument_onboarding_v2.py").read_text(encoding="utf-8")
    page_source = (ROOT / "pages" / "1_Product_Browser.py").read_text(encoding="utf-8")

    assert "Saxo Product Explorer" in explorer_source
    assert "IncludeNonTradable" in explorer_source
    assert "Kontokontekst" in explorer_source
    assert "Produktkategori" in explorer_source
    assert "Retning" in explorer_source
    assert "Rå Saxo-data" in explorer_source
    assert "Legg til i PriceGauger v2" in explorer_source
    assert "onboard_saxo_instrument_v2" in explorer_source
    assert "canonical 1m" in explorer_source
    assert "render_saxo_product_explorer()" in page_source

    # UI owns confirmation, not SQL or Saxo execution.
    assert ".place_order(" not in explorer_source
    assert ".precheck(" not in explorer_source
    assert "execute_confirmed_manual_order" not in explorer_source
    assert "INSERT " not in explorer_source.upper()
    assert "UPDATE " not in explorer_source.upper()
    assert "trade/v2/orders" not in explorer_source

    # The bounded onboarding service may write only canonical registry/subscription tables.
    assert "pg_v2_markets" in onboarding_source
    assert "pg_v2_instruments" in onboarding_source
    assert "pg_v2_instrument_sources" in onboarding_source
    assert "pg_v2_collection_subscriptions" in onboarding_source
    assert "pg_v2_forecasts" not in onboarding_source
    assert "pg_v2_ai_decisions" not in onboarding_source
    assert "trade/v2/orders" not in onboarding_source
