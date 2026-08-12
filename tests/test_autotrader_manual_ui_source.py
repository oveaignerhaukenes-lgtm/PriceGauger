from pathlib import Path


def test_manual_autotrader_flow_stays_inside_tradingdesk_panel() -> None:
    source = Path("trading_desk_product_panel.py").read_text(encoding="utf-8")

    assert 'st.subheader("AutoTrader · Saxo SIM")' in source
    assert '"Kjør Saxo pre-check"' in source
    assert '"Jeg bekrefter denne eksakte Saxo SIM-ordren"' in source
    assert '"Send SIM-ordre"' in source
    assert "execute_confirmed_manual_order" in source
    assert "PreTradeDisclaimers" in source
    assert "open_orders" in source
    assert "net_positions" in source


def test_saxo_connect_page_is_not_modified_into_an_order_ui() -> None:
    source = Path("pages/1_Saxo_OpenAPI.py").read_text(encoding="utf-8")

    assert "Send SIM-ordre" not in source
    assert "execute_confirmed_manual_order" not in source
