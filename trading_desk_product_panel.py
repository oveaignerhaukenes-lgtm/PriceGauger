from __future__ import annotations

import streamlit as st

from saxo_provider import SaxoError
from saxo_trading import SaxoTradingSafetyError, configured_trading_client
from trading_desk_products import (
    LeveragedProduct,
    discover_leveraged_products,
    product_details,
    product_label,
)


def _state_key(prefix: str, market: str) -> str:
    return f"tradingdesk_products_{prefix}_{market}"


def render_saxo_product_panel(market: str) -> None:
    st.divider()
    st.subheader("Saxo-produkter")
    st.caption(
        "Read-only produktvalg for markedet i grafen. Søket viser Mini Futures og KO-produkter "
        "fra Saxo SIM; ingen ordre kan sendes fra dette panelet ennå."
    )

    try:
        trading = configured_trading_client()
    except SaxoTradingSafetyError as exc:
        st.error(str(exc))
        return
    except Exception as exc:
        st.warning(f"Kunne ikke initialisere Saxo SIM for instrumentsøk: {exc}")
        return

    if trading is None:
        st.info("Koble til Saxo SIM for å søke etter handlebare produkter.")
        return

    products_key = _state_key("list", market)
    details_key = _state_key("details", market)

    if st.button("Finn Mini/KO-produkter hos Saxo", key=f"product_search_{market}"):
        try:
            with st.spinner(f"Søker Saxo SIM etter produkter relatert til {market} …"):
                products = discover_leveraged_products(trading.client, market)
            st.session_state[products_key] = products
            st.session_state.pop(details_key, None)
        except SaxoError as exc:
            st.error(str(exc))
            return
        except Exception as exc:
            st.error(f"Produktsøket feilet: {exc}")
            return

    products = st.session_state.get(products_key)
    if products is None:
        return
    if not products:
        st.info(f"Saxo SIM returnerte ingen Mini/KO-produkter for {market} med dagens søkekriterier.")
        return

    known_long = sum(product.direction == "Long" for product in products)
    known_short = sum(product.direction == "Short" for product in products)
    unknown = len(products) - known_long - known_short
    st.caption(
        f"Fant {len(products)} produkter · Long {known_long} · Short {known_short}"
        + (f" · retning ukjent {unknown}" if unknown else "")
    )

    selected: LeveragedProduct = st.selectbox(
        "Produkt",
        products,
        format_func=product_label,
        key=f"product_select_{market}",
    )

    selection_key = f"{selected.instrument.uic}:{selected.instrument.asset_type}"
    cached = st.session_state.get(details_key)
    if not isinstance(cached, dict) or cached.get("selection") != selection_key:
        try:
            with st.spinner("Henter Saxo-instrumentdetaljer …"):
                details = product_details(trading.client, selected)
            st.session_state[details_key] = {"selection": selection_key, "value": details}
        except SaxoError as exc:
            st.warning(f"Fant produktet, men kunne ikke hente detaljene: {exc}")
            details = None
        except Exception as exc:
            st.warning(f"Fant produktet, men detaljoppslaget feilet: {exc}")
            details = None
    else:
        details = cached.get("value")

    instrument = selected.instrument
    st.write(f"**{instrument.description or instrument.symbol or 'Saxo-instrument'}**")
    st.caption(f"{instrument.asset_type} · UIC {instrument.uic} · symbol {instrument.symbol or 'ikke oppgitt'}")

    if details is None:
        return

    direction_col, barrier_col, financing_col, tradable_col = st.columns(4)
    direction_col.metric("Retning", details.direction or "Ukjent")
    barrier_col.metric("KO / barrier", f"{details.barrier:g}" if details.barrier is not None else "Ikke oppgitt")
    financing_col.metric(
        "Finansieringsnivå",
        f"{details.financing_level:g}" if details.financing_level is not None else "Ikke oppgitt",
    )
    tradable_label = "Ukjent"
    if details.is_tradable is True:
        tradable_label = "Ja"
    elif details.is_tradable is False:
        tradable_label = "Nei"
    tradable_col.metric("Tradable", tradable_label)

    extras: list[str] = []
    if details.currency:
        extras.append(f"valuta {details.currency}")
    if details.strike is not None:
        extras.append(f"strike {details.strike:g}")
    if details.default_amount is not None:
        extras.append(f"default amount {details.default_amount:g}")
    if extras:
        st.caption(" · ".join(extras))

    st.info(
        "Produktet er foreløpig bare valgt for inspeksjon. Kjøp/salg kobles senere til Saxo pre-check "
        "og eksplisitt SIM-bekreftelse; denne capability-en sender ingen ordre."
    )
