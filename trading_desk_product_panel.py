from __future__ import annotations

import streamlit as st

from autotrader_manual_execution import (
    ManualExecutionResult,
    build_manual_order_intent,
    execute_confirmed_manual_order,
    precheck_is_clear,
    validate_manual_intent,
)
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


def _clear_execution_state(market: str) -> None:
    for prefix in ("order_preview", "manual_intent", "precheck", "execution_result"):
        st.session_state.pop(_state_key(prefix, market), None)


def render_saxo_product_panel(market: str) -> None:
    st.divider()
    st.subheader("AutoTrader · Saxo SIM")
    st.caption(
        "Manuell ordreplassering for markedet i TradingDesk. Hele execution-flyten ligger her under "
        "AutoTrader; Saxo-siden brukes bare til OAuth/tilkobling. Ordren er hardlåst til SIM."
    )

    try:
        trading = configured_trading_client()
    except SaxoTradingSafetyError as exc:
        st.error(str(exc))
        return
    except Exception as exc:
        st.warning(f"Kunne ikke initialisere Saxo SIM for AutoTrader: {exc}")
        return

    if trading is None:
        st.info("Koble til Saxo SIM fra Saxo-siden først. AutoTrader bruker den delte OAuth-tilkoblingen.")
        return

    products_key = _state_key("list", market)
    details_key = _state_key("details", market)
    preview_key = _state_key("order_preview", market)
    intent_key = _state_key("manual_intent", market)
    precheck_key = _state_key("precheck", market)
    result_key = _state_key("execution_result", market)
    submitted_key = "autotrader_manual_submitted_intent_ids"
    submitted = st.session_state.setdefault(submitted_key, set())

    if st.button("Finn Mini/KO-produkter hos Saxo", key=f"product_search_{market}"):
        try:
            with st.spinner(f"Søker Saxo SIM etter produkter relatert til {market} …"):
                products = discover_leveraged_products(trading.client, market)
            st.session_state[products_key] = products
            st.session_state.pop(details_key, None)
            _clear_execution_state(market)
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
            _clear_execution_state(market)
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
    st.subheader("Manuell ordre")
    st.caption(
        "KJØP/SELG gjelder det konkrete produktet over. Et Mini Short-produkt kjøpes for short-eksponering; "
        "SELG betyr salg av valgt produkt, ikke automatisk short av underliggende."
    )

    try:
        accounts = tuple(account for account in trading.accounts() if account.active)
    except Exception as exc:
        accounts = ()
        st.warning(f"Kunne ikke hente SIM-kontoer: {exc}")

    if not accounts:
        st.info("Ingen aktiv Saxo SIM-konto er tilgjengelig.")
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
            preview = build_order_preview(
                market=market,
                product=selected,
                account_key=account.account_key,
                account_id=account.account_id,
                action=action,
                amount=float(amount),
            )
            intent = build_manual_order_intent(preview)
            validate_manual_intent(intent, active_account_keys={item.account_key for item in accounts})
            st.session_state[preview_key] = preview
            st.session_state[intent_key] = intent
            st.session_state.pop(precheck_key, None)
            st.session_state.pop(result_key, None)
        except ValueError as exc:
            st.error(str(exc))

    preview = st.session_state.get(preview_key)
    intent = st.session_state.get(intent_key)
    if preview is None or intent is None:
        st.info("Velg produkt, konto og antall, og forbered KJØP eller SELG. Ingenting sendes før pre-check og ny bekreftelse.")
        return

    st.markdown("**Ordreintent**")
    st.write(
        f"{preview.action_label} **{preview.amount:g} × "
        f"{preview.description or preview.symbol or 'Saxo-instrument'}**"
    )
    st.caption(
        f"{preview.market} · {preview.asset_type} · UIC {preview.uic} · konto {preview.account_id} · "
        f"{preview.exposure_label}"
    )
    st.caption(f"Intent-ID: {intent.intent_id}")

    if st.button("Kjør Saxo pre-check", type="primary", key=f"manual_precheck_{market}"):
        try:
            validate_manual_intent(intent, active_account_keys={item.account_key for item in accounts})
            with st.spinner("Validerer ordren hos Saxo SIM …"):
                precheck = trading.precheck(intent.order_request())
            st.session_state[precheck_key] = {"intent_id": intent.intent_id, "value": precheck}
        except (SaxoError, ValueError, SaxoTradingSafetyError) as exc:
            st.error(str(exc))
        except Exception as exc:
            st.error(f"Pre-check feilet: {exc}")

    cached_precheck = st.session_state.get(precheck_key)
    precheck = None
    if isinstance(cached_precheck, dict) and cached_precheck.get("intent_id") == intent.intent_id:
        precheck = cached_precheck.get("value")

    if not isinstance(precheck, dict):
        return

    precheck_result = str(precheck.get("PreCheckResult") or "UKJENT")
    if precheck_result.lower() == "ok":
        st.success("Saxo pre-check: OK")
    else:
        st.warning(f"Saxo pre-check: {precheck_result}")
    with st.expander("Se pre-check-respons"):
        st.json(precheck)

    disclaimers = precheck.get("PreTradeDisclaimers")
    if disclaimers:
        st.error(
            "Saxo krever pre-trade disclaimer for denne ordren. AutoTrader sender ikke ordren før "
            "en eksplisitt disclaimer-flyt er implementert."
        )
        return
    if not precheck_is_clear(precheck):
        st.warning("Ordren kan ikke sendes fordi Saxo pre-check ikke er klarert.")
        return

    st.markdown("**Eksplisitt bekreftelse**")
    st.warning(
        f"Neste knapp sender en faktisk ordre til Saxo SIM: {preview.action_label} {preview.amount:g} × "
        f"{preview.description or preview.symbol or 'instrument'} på konto {preview.account_id}."
    )
    confirmed = st.checkbox(
        "Jeg bekrefter denne eksakte Saxo SIM-ordren",
        key=f"manual_confirm_{intent.intent_id}",
    )
    already_submitted = intent.intent_id in submitted
    if already_submitted:
        st.info("Dette intentet er allerede forsøkt sendt. Automatisk retry er blokkert for å unngå dobbeltordre.")

    if st.button(
        "Send SIM-ordre",
        type="primary",
        disabled=not confirmed or already_submitted,
        key=f"manual_send_{intent.intent_id}",
    ):
        try:
            validate_manual_intent(intent, active_account_keys={item.account_key for item in accounts})
            with st.spinner("Sender én manuell ordre til Saxo SIM og leser tilbake Saxo-state …"):
                result = execute_confirmed_manual_order(
                    trading,
                    intent,
                    confirmed_intent_id=intent.intent_id,
                    submitted_intent_ids=submitted,
                )
            st.session_state[result_key] = result
        except (SaxoError, ValueError, SaxoTradingSafetyError) as exc:
            st.error(str(exc))
            if intent.intent_id in submitted:
                st.warning(
                    "Ordreforsøket er markert som brukt. Ved timeout/ukjent respons sendes det ikke automatisk på nytt; "
                    "kontroller Saxo-state før du bygger et nytt intent."
                )
        except Exception as exc:
            st.error(f"Ordreforsøket feilet: {exc}")
            if intent.intent_id in submitted:
                st.warning("Automatisk retry er blokkert. Kontroller Saxo-state før et eventuelt nytt ordreintent.")

    result = st.session_state.get(result_key)
    if not isinstance(result, ManualExecutionResult) or result.intent_id != intent.intent_id:
        return

    st.success(f"Saxo SIM svarte på ordreforespørselen. OrderId: {result.order_id or 'ikke oppgitt'}")
    with st.expander("Saxo ordrespons"):
        st.json(result.order_response)

    st.markdown("**Authoritative Saxo read-back**")
    if result.open_orders:
        st.caption(f"Saxo rapporterer {len(result.open_orders)} matching åpen ordre/ordre(r) for UIC {preview.uic}.")
        with st.expander("Åpne ordre"):
            st.json(list(result.open_orders))
    else:
        st.caption("Ingen matching åpen ordre rapporteres. En market-order kan allerede være fylt eller avvist; se nettoposisjon og ordrespons.")

    if result.net_positions:
        st.caption(f"Saxo rapporterer {len(result.net_positions)} matching nettoposisjon(er) for UIC {preview.uic}.")
        with st.expander("Nettoposisjon"):
            st.json(list(result.net_positions))
    else:
        st.caption("Ingen matching nettoposisjon rapporteres i umiddelbar read-back.")
