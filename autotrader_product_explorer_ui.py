from __future__ import annotations

import streamlit as st

from autotrader_product_explorer import (
    CATEGORY_OPTIONS,
    DIRECTION_OPTIONS,
    ProductSearchRequest,
    ProductSearchResult,
    ProductSummary,
    detail_rows,
    load_product_details,
    product_education_links,
    product_explanation,
    search_product_universe,
)
from database import using_postgres
from instrument_onboarding_v2 import (
    SaxoInstrumentOnboardingRequestV2,
    onboard_saxo_instrument_v2,
)
from saxo_provider import SaxoError
from saxo_trading import SaxoAccount, SaxoTradingSafetyError, configured_trading_client


_RESULT_KEY = "saxo_product_explorer_result_v2"
_DETAILS_KEY = "saxo_product_explorer_details_v2"
_ONBOARDING_RESULT_KEY = "saxo_product_explorer_onboarding_result_v2"
_MARKET_CATEGORIES = (
    "commodity",
    "equity",
    "index",
    "fx",
    "fixed_income",
    "fund",
    "other",
)


def _account_label(account: SaxoAccount) -> str:
    active = "aktiv" if account.active else "inaktiv"
    suffix = f" · {account.currency}" if account.currency else ""
    return f"{account.account_id}{suffix} · {active}"


def _product_label(product: ProductSummary) -> str:
    description = product.instrument.description or product.instrument.symbol or f"UIC {product.instrument.uic}"
    return (
        f"{description} · {product.category} · {product.direction} · "
        f"{product.instrument.asset_type} · UIC {product.instrument.uic}"
    )


def _result_rows(result: ProductSearchResult) -> list[dict[str, object]]:
    return [
        {
            "Produkt": product.instrument.description or product.instrument.symbol,
            "Kategori": product.category,
            "Retning*": product.direction,
            "AssetType": product.instrument.asset_type,
            "UIC": product.instrument.uic,
            "Symbol": product.instrument.symbol,
            "Valuta": product.currency or "",
            "Børs": product.exchange or "",
            "Tradable": "Ja" if product.is_tradable else "Nei",
            "NonTradableReason": product.non_tradable_reason or "",
            "TradableAs": ", ".join(product.tradable_as),
        }
        for product in result.products
    ]


def _request_caption(result: ProductSearchResult) -> str:
    request = result.request
    account = "uten AccountKey" if not request.account_key else "med valgt SIM AccountKey"
    non_tradable = "inkl. non-tradable" if request.include_non_tradable else "kun standard tradable-søk"
    return (
        f"Saxo-søk: `{request.keywords}` · {request.category} · {request.direction} · "
        f"{account} · {non_tradable} · rå treff {result.raw_count} · viste treff {len(result.products)}"
    )


def _detail_cache_key(product: ProductSummary, account_key: str | None) -> str:
    return f"{product.instrument.uic}:{product.instrument.asset_type}:{account_key or '-'}"


def _suggest_market_category(product: ProductSummary) -> str:
    underlying = (product.underlying_asset_type or "").lower()
    asset_type = product.instrument.asset_type.lower()
    if "stockindex" in underlying or "index" in asset_type:
        return "index"
    if underlying == "stock" or product.category == "Aksjer":
        return "equity"
    if asset_type.startswith("fx") or product.category == "Valuta":
        return "fx"
    if product.category == "Obligasjoner":
        return "fixed_income"
    if product.category in {"ETF / ETC / ETN", "Fond"}:
        return "fund"
    return "other"


def _onboarding_metadata(product: ProductSummary, details: dict[str, object]) -> dict[str, object]:
    return {
        "description": product.instrument.description,
        "currency": product.currency,
        "exchange": product.exchange,
        "expiry": product.instrument.expiry,
        "underlying_asset_type": product.underlying_asset_type,
        "tradable_as": list(product.tradable_as),
        "product_category": product.category,
        "details_description": details.get("Description"),
    }


def _render_onboarding(
    *,
    selected: ProductSummary,
    result: ProductSearchResult,
    details: dict[str, object],
) -> None:
    st.divider()
    st.markdown("### Legg til i PriceGauger v2")
    st.caption(
        "Dette er en systemkonfigurasjons-write: valgt Saxo-instrument registreres i canonical v2-registry "
        "og 1m collection subscription aktiveres. Det sender ingen ordre."
    )

    if not using_postgres():
        st.warning("Onboarding er deaktivert: canonical v2-registry krever konfigurert PostgreSQL.")
        return

    identity = f"UIC {selected.instrument.uic} · {selected.instrument.asset_type}"
    st.code(identity, language=None)

    default_market = result.request.keywords.strip() or selected.instrument.description or selected.instrument.symbol
    default_category = _suggest_market_category(selected)
    category_index = _MARKET_CATEGORIES.index(default_category)

    with st.form(f"v2_onboarding_{selected.instrument.uic}_{selected.instrument.asset_type}"):
        market_name = st.text_input(
            "Canonical market-navn",
            value=default_market,
            help=(
                "Dette er den stabile økonomiske markedsidentiteten, f.eks. Gold, Apple eller DAX — "
                "ikke nødvendigvis det fulle Saxo-produktnavnet. Flere konkrete instrumenter kan senere høre til samme marked."
            ),
        )
        market_category = st.selectbox(
            "Økonomisk markedskategori",
            _MARKET_CATEGORIES,
            index=category_index,
            help="Klassifiser selve markedet/underliggende økonomisk mål, ikke Saxos produkttype.",
        )
        display_name = st.text_input(
            "Instrumentnavn i registry",
            value=selected.instrument.description or selected.instrument.symbol or identity,
        )
        confirm = st.checkbox(
            f"Jeg bekrefter {identity} → `{market_name or '…'}` og aktivering av canonical 1m-innsamling.",
            value=False,
        )
        submit_onboarding = st.form_submit_button(
            "Legg til i PriceGauger",
            type="primary",
            use_container_width=True,
        )

    if not submit_onboarding:
        return
    if not confirm:
        st.warning("Bekreft den eksakte registry-endringen før du fortsetter.")
        return
    if not market_name.strip() or not display_name.strip():
        st.error("Canonical market-navn og instrumentnavn må være utfylt.")
        return

    try:
        onboarded = onboard_saxo_instrument_v2(
            SaxoInstrumentOnboardingRequestV2(
                market_name=market_name,
                market_category=market_category,
                display_name=display_name,
                uic=selected.instrument.uic,
                asset_type=selected.instrument.asset_type,
                symbol=selected.instrument.symbol or None,
                price_multiplier=selected.instrument.price_multiplier,
                metadata=_onboarding_metadata(selected, details),
            )
        )
    except (ValueError, LookupError, RuntimeError) as exc:
        st.error(f"V2-onboarding ble avvist uten delvis registry-write: {exc}")
        return

    st.session_state[_ONBOARDING_RESULT_KEY] = onboarded
    action = "Gjenbrukte eksisterende source og aktiverte subscription" if onboarded.reused_existing_source else "Registrert"
    st.success(
        f"{action}: market_id={onboarded.market_id}, instrument_id={onboarded.instrument_id}, "
        f"source_id={onboarded.instrument_source_id}. Canonical 1m subscription er aktiv."
    )


def render_saxo_product_explorer() -> None:
    st.subheader("Saxo Product Explorer")
    st.caption(
        "Katalogvisning av instrumentuniverset Saxo SIM eksponerer. Søk/Inspector er read-only; "
        "eksplisitt `Legg til i PriceGauger` kan registrere valgt instrument i canonical v2-registry."
    )

    try:
        trading = configured_trading_client()
    except SaxoTradingSafetyError as exc:
        st.error(str(exc))
        return
    if trading is None:
        st.info("Koble til Saxo SIM først for å bruke Product Explorer.")
        return

    try:
        accounts = tuple(account for account in trading.accounts() if account.active)
    except SaxoError as exc:
        st.warning(f"Kunne ikke lese Saxo-kontoer: {exc}")
        accounts = ()

    account_options: list[SaxoAccount | None] = [None, *accounts]
    with st.form("saxo_product_explorer_search"):
        search_col, category_col, direction_col = st.columns([2.2, 1.35, 1.15])
        with search_col:
            keywords = st.text_input(
                "Søk i Saxo-katalogen",
                placeholder="Gold, XAU, Apple, Brent, DAX …",
                help="Saxo søker i instrumentnavn/symboler innenfor brukerens tilgjengelige produktunivers.",
            )
        with category_col:
            category = st.selectbox("Produktkategori", CATEGORY_OPTIONS)
        with direction_col:
            direction = st.selectbox(
                "Retning",
                DIRECTION_OPTIONS,
                help=(
                    "Retning i søkeresultatet tolkes fra Saxos produktnavn/symbol "
                    "(Bull/Long/Call eller Bear/Short/Put). Det er ikke et autoritativt API-felt."
                ),
            )

        option_col, account_col, limit_col = st.columns([1.2, 1.65, 0.8])
        with option_col:
            include_non_tradable = st.checkbox(
                "Vis non-tradable",
                value=False,
                help="Sender IncludeNonTradable=true til Saxos instrument-search.",
            )
        with account_col:
            account = st.selectbox(
                "Kontokontekst",
                account_options,
                format_func=lambda value: "Uten AccountKey" if value is None else _account_label(value),
                help="Med AccountKey evaluerer Saxo instrumenttilgang for den valgte SIM-kontoen.",
            )
        with limit_col:
            top = st.selectbox("Maks treff", (50, 100, 200), index=1)

        submitted = st.form_submit_button("Søk Saxo", type="primary", use_container_width=True)

    if submitted:
        if not keywords.strip():
            st.warning("Skriv inn minst ett søkeord.")
        else:
            request = ProductSearchRequest(
                keywords=keywords,
                category=category,
                direction=direction,
                include_non_tradable=include_non_tradable,
                account_key=account.account_key if account is not None else None,
                top=top,
            )
            try:
                st.session_state[_RESULT_KEY] = search_product_universe(trading.client, request)
                st.session_state.pop(_ONBOARDING_RESULT_KEY, None)
            except SaxoError as exc:
                st.session_state.pop(_RESULT_KEY, None)
                st.error(f"Saxo instrument-search feilet: {exc}")

    result = st.session_state.get(_RESULT_KEY)
    if not isinstance(result, ProductSearchResult):
        st.info("Søk etter et marked eller produkt for å se hva Saxo SIM faktisk eksponerer.")
        return

    st.caption(_request_caption(result))
    if not result.products:
        st.warning(
            "Ingen treff etter valgt filter. Prøv `Alle`, slå på non-tradable eller sammenlign med/uten AccountKey "
            "før du konkluderer med at produktfamilien ikke er tilgjengelig."
        )
        return

    list_col, inspector_col = st.columns([2.2, 1.25], gap="large")
    with list_col:
        st.dataframe(
            _result_rows(result),
            use_container_width=True,
            hide_index=True,
            height=min(620, 92 + 35 * min(len(result.products), 15)),
        )
        st.caption(
            "*Retning er en eksplisitt navnetolkning, ikke et Direction-felt fra Saxo instrument-summary. "
            "UIC + AssetType er den tekniske Saxo-identiteten som vises uendret."
        )
        selected = st.selectbox(
            "Velg produkt for forklaring",
            result.products,
            format_func=_product_label,
            key="saxo_product_explorer_selected_v2",
        )

    with inspector_col:
        st.markdown("### Valgt produkt")
        st.markdown(f"**{selected.instrument.description or selected.instrument.symbol}**")
        st.caption(
            f"{selected.category} · {selected.direction} · {selected.instrument.asset_type} · "
            f"UIC {selected.instrument.uic}"
        )
        st.write(product_explanation(selected))

        if selected.direction != "Ukjent":
            st.caption("Bull/Bear/Long/Short her er tolket fra Saxos navn/symbol og bør kontrolleres mot produktvilkårene.")

        detail_account_key = result.request.account_key
        cache = st.session_state.setdefault(_DETAILS_KEY, {})
        cache_key = _detail_cache_key(selected, detail_account_key)
        if cache_key not in cache:
            try:
                cache[cache_key] = load_product_details(
                    trading.client,
                    selected,
                    account_key=detail_account_key,
                )
            except SaxoError as exc:
                cache[cache_key] = {"_error": str(exc)}

        details = cache.get(cache_key, {})
        clean_details: dict[str, object] = {}
        if isinstance(details, dict) and details.get("_error"):
            st.warning(f"Kunne ikke hente instrumentdetaljer: {details['_error']}")
        elif isinstance(details, dict):
            clean_details = details
            rows = detail_rows(details)
            if rows:
                st.dataframe(
                    [{"Felt": label, "Verdi": value} for label, value in rows],
                    use_container_width=True,
                    hide_index=True,
                )

        for label, url in product_education_links(selected):
            st.markdown(f"[{label}]({url})")

        with st.expander("Rå Saxo-data", expanded=False):
            st.markdown("**Search summary**")
            st.json(selected.raw)
            if clean_details:
                st.markdown("**Instrument details**")
                st.json(clean_details)

        _render_onboarding(selected=selected, result=result, details=clean_details)
