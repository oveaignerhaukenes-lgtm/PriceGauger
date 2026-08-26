from __future__ import annotations

import streamlit as st

from autotrader_product_scanner_v2 import (
    ProductScanResultV2,
    SCANNER_MARKET_SEARCH_TERMS,
    candidate_rows_for_ui_v2,
    diagnostic_rows_for_ui_v2,
    scan_saxo_candidates_v2,
)
from saxo_provider import configured_client


_SCAN_KEY = "autotrader_product_scanner_v2"


def render_product_scanner_v2() -> None:
    st.subheader("AutoTrader Product Scanner")
    st.caption(
        "Read-only inspeksjon av Saxo-kandidater mot PriceGaugers separate AutoTrader-univers. "
        "Saxo kan foreslå produkter; bare eksplisitt verifiserte PG-identiteter kan senere bli execution-eligible."
    )

    try:
        client = configured_client()
    except Exception as exc:
        st.warning(f"Kunne ikke initialisere Saxo for scanner: {exc}")
        return
    if client is None:
        st.info("Koble til Saxo først for å kjøre Product Scanner.")
        return

    environment = "LIVE" if "gateway.saxobank.com/openapi" in client.base_url.lower() else "SIM"
    st.caption(
        f"Scanner leser Saxo {environment} read-only. Dette gir ingen execution-authority; "
        "ordre- og entry-klientene beholder sine egne separate sikkerhetsporter."
    )

    left, right = st.columns([2, 1])
    market = left.selectbox(
        "Marked for scanning",
        tuple(SCANNER_MARKET_SEARCH_TERMS),
        key="autotrader_scanner_market",
    )
    limit = right.selectbox("Maks produkter", (10, 20, 40), index=1, key="autotrader_scanner_limit")

    if st.button("Scan kandidater", type="primary", key="autotrader_scan_products"):
        with st.spinner(f"Kartlegger Saxo-universet og inspiserer opptil {limit} kandidater for {market} …"):
            st.session_state[_SCAN_KEY] = scan_saxo_candidates_v2(
                client,
                market=market,
                max_products=int(limit),
            )

    result = st.session_state.get(_SCAN_KEY)
    if not isinstance(result, ProductScanResultV2):
        st.info("Kjør en scan for å se Saxo-univers, pris/spread, minste størrelse og kostnadsillustrasjon.")
        return

    st.caption(
        f"{result.market}: fant {result.discovered} strukturerte kandidater via markedssøk · "
        f"inspiserte {result.inspected} · feil {result.failed}."
    )

    status_cols = st.columns(4)
    status_cols[0].metric(
        "Structured synlig",
        "?" if result.structured_universe_count is None else result.structured_universe_count,
    )
    status_cols[1].metric(
        "CATS synlig",
        "?" if result.cats_universe_count is None else result.cats_universe_count,
    )
    zero_commission = sum(1 for row in result.rows if row.zero_commission is True)
    status_cols[2].metric("0-kommisjon kandidater", zero_commission)
    status_cols[3].metric("Execution-eligible", sum(1 for row in result.rows if row.pg_eligible))

    if result.account_labels:
        st.caption("Søk evalueres mot aktiv Saxo-konto: " + ", ".join(result.account_labels))

    if not result.rows:
        if result.structured_universe_count == 0:
            st.warning(
                "Saxo-kontoen eksponerer ingen produkter i de strukturerte produktfamiliene scanneren undersøker. "
                "Da er 0 treff sannsynligvis kontotilgang/jurisdiksjon, ikke bare feil søkeord."
            )
        else:
            st.warning(
                "Kontoen ser ut til å ha strukturerte produkter, men ingen ble koblet til dette markedet med de utvidede "
                "Saxo-søkeordene. Åpne søkediagnostikken under for å se nøyaktig hvilke aliaser som ga treff."
            )
        if result.cats_universe_count == 0:
            st.info(
                "Ingen CATS-produkter er synlige for kontoen i denne scannen. CATS er spesielt interessant fordi Saxo "
                "har en dokumentert 0-kurtasje Turbo-serie på enkelte kontoer/jurisdiksjoner."
            )
    else:
        st.dataframe(
            candidate_rows_for_ui_v2(result.rows),
            use_container_width=True,
            hide_index=True,
            height=min(680, 110 + 35 * min(len(result.rows), 16)),
        )
        st.caption(
            "* Kommisjon og Total kost % hentes fra Saxos read-only pre-trade cost illustration når endpointet støtter "
            "produktet. 0 kommisjon betyr bare 0 eksplisitt kurtasje i illustrasjonen; spread, finansiering, FX, skatt og "
            "andre produktkostnader kan fortsatt finnes. Dette er ikke en fill-garanti."
        )

        in_universe = [row for row in result.rows if row.in_pg_universe]
        if not in_universe:
            st.info(
                "PG-universet er foreløpig tomt. Scannerfunn blir aldri automatisk godkjent: limited-loss, ingen åpen "
                "marginforpliktelse og kostnadsprofil må verifiseres før en eksakt UIC/AssetType-identitet tillates."
            )

    with st.expander("Saxo søkediagnostikk", expanded=not bool(result.rows)):
        st.caption(
            "Diagnostikken viser account-aware treff for hele det strukturerte universet, CATS-børsen og hvert eksplisitt "
            "markedsalias. Dette skiller 'Saxo tilbyr det ikke på kontoen' fra 'søkeordet traff ikke'."
        )
        if result.diagnostics:
            st.dataframe(
                diagnostic_rows_for_ui_v2(result.diagnostics),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("Ingen søkediagnostikk tilgjengelig.")
