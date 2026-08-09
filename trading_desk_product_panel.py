from __future__ import annotations

import streamlit as st

from saxo_provider import SaxoError
from saxo_trading import SaxoTradingSafetyError, configured_trading_client
from trading_desk_order_preview import build_order_preview
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
        "Produktvalg og ordregrensesnitt for markedet i grafen. Mini Futures og KO-produkter "
        "hentes fra Saxo SIM. Ordregrensesnittet er foreløpig kun en lokal forhåndsvisning: "
        "ingen pre-check eller ordre kan sendes her ennå."
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
    preview_key = _state_key("order_preview", market)

    if st.button("Finn Mini/KO-produkter hos Saxo", key=f"product_search_{market}"):
        try:
            with st.spinner(f"Søker Saxo SIM etter produkter relatert til {market} …"):
                products = discover_leveraged_products(trading.client, market)
            st.session_state[products_key] = products
            st.session_state.pop(details_key, None)
            st.session_state.pop(preview_key, None)
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
            st.session_state.pop(preview_key, None)
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

    if details is not None:
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

    st.divider()
    st.subheader("Handel · grensesnittskisse")
    st.caption(
        "Produktet over er det konkrete Saxo-instrumentet som skal handles. Et Mini Short-produkt "
        "kjøpes for short-eksponering; SELG betyr salg av det valgte produktet, ikke automatisk short av underliggende."
    )

    try:
        accounts = tuple(account for account in trading.accounts() if account.active)
    except Exception as exc:
        accounts = ()
        st.warning(f"Kunne ikke hente SIM-kontoer til ordregrensesnittet: {exc}")

    if not accounts:
        st.info("Ingen aktiv Saxo SIM-konto er tilgjengelig for ordre-forhåndsvisning.")
        return

    account = st.selectbox(
        "Saxo SIM-konto",
        accounts,
        format_func=lambda value: f"{value.account_id} · {value.currency or 'valuta ukjent'}",
        key=f"trade_account_{market}",
    )
    default_amount = 1.0
    if details is not None and details.default_amount is not None and details.default_amount > 0:
        default_amount = float(details.default_amount)
    amount = st.number_input(
        "Antall",
        min_value=0.000001,
        value=float(default_amount),
        step=1.0,
        format="%.6f",
        key=f"trade_amount_{market}",
    )

    buy_col, sell_col = st.columns(2)
    prepare_buy = buy_col.button("Forbered KJØP", type="primary", key=f"prepare_buy_{market}")
    prepare_sell = sell_col.button("Forbered SELG", key=f"prepare_sell_{market}")

    action = "Buy" if prepare_buy else "Sell" if prepare_sell else None
    if action is not None:
        try:
            st.session_state[preview_key] = build_order_preview(
                market=market,
                product=selected,
                account_key=account.account_key,
                account_id=account.account_id,
                action=action,
                amount=float(amount),
            )
        except ValueError as exc:
            st.error(str(exc))

    preview = st.session_state.get(preview_key)
    if preview is None:
        st.info("KJØP/SELG bygger foreløpig bare en lokal ordre-forhåndsvisning. Ingenting sendes til Saxo.")
        return

    st.markdown("**Ordre-forhåndsvisning**")
    st.write(
        f"{preview.action_label} **{preview.amount:g} × "
        f"{preview.description or preview.symbol or 'Saxo-instrument'}**"
    )
    st.caption(
        f"{preview.market} · {preview.asset_type} · UIC {preview.uic} · "
        f"konto {preview.account_id} · {preview.exposure_label}"
    )

    precheck_col, send_col = st.columns(2)
    precheck_col.button(
        "Kjør Saxo pre-check · låst",
        disabled=True,
        key=f"locked_precheck_{market}",
    )
    send_col.button(
        "Send SIM-ordre · låst",
        disabled=True,
        key=f"locked_send_{market}",
    )
    st.warning(
        "Ordrebanen stopper her i denne capability-en. Neste steg er å koble denne eksakte "
        "forhåndsvisningen til Saxo pre-check, deretter en separat eksplisitt bekreftelse før SIM-order kan sendes."
    )
