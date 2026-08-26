from __future__ import annotations

import streamlit as st

from autotrader_product_scanner_v2 import (
    ProductScanResultV2,
    SCANNER_MARKET_SEARCH_TERMS,
    candidate_rows_for_ui_v2,
    diagnostic_rows_for_ui_v2,
    scan_saxo_candidates_v2,
)
from saxo_market_inventory_v2 import (
    SaxoMarketInventoryResultV2,
    asset_type_rows_for_ui_v2,
    inventory_query_rows_for_ui_v2,
    market_inventory_rows_for_ui_v2,
    scan_saxo_market_inventory_v2,
)
from saxo_provider import configured_client


_SCAN_KEY = "autotrader_product_scanner_v2"
_INVENTORY_KEY = "autotrader_saxo_market_inventory_v2"


def render_product_scanner_v2() -> None:
    st.subheader("AutoTrader Product Scanner")
    st.caption(
        "Read-only kartlegging av Saxo-markedet før PriceGauger filtrerer kandidater. "
        "Først listes alt kontoen kan se for valgt marked uten produktfilter; deretter vurderes aktuelle AutoTrader-familier."
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
    limit = right.selectbox("Maks kandidater å kostnadsanalysere", (10, 20, 40), index=1, key="autotrader_scanner_limit")

    if st.button("Kartlegg marked", type="primary", key="autotrader_scan_products"):
        with st.spinner(f"Lister Saxo-treff for {market} uten produktfilter …"):
            st.session_state[_INVENTORY_KEY] = scan_saxo_market_inventory_v2(
                client,
                market=market,
                max_per_query=250,
            )
        with st.spinner(f"Filtrerer og kostnadsanalyserer opptil {limit} strukturerte kandidater …"):
            st.session_state[_SCAN_KEY] = scan_saxo_candidates_v2(
                client,
                market=market,
                max_products=int(limit),
            )

    inventory = st.session_state.get(_INVENTORY_KEY)
    result = st.session_state.get(_SCAN_KEY)
    if not isinstance(inventory, SaxoMarketInventoryResultV2) or not isinstance(result, ProductScanResultV2):
        st.info("Kjør kartleggingen for å se hele Saxo-markedsinventaret før kandidatfiltrering.")
        return

    st.markdown("### 1. Saxo-markedsinventar · uten produktfilter")
    st.caption(
        "Dette er første kontrollpunkt: alle unike account-aware instrumenttreff Saxo returnerer for markedsaliasene, "
        "uten at PG på forhånd begrenser AssetType. Tabellen viser derfor også futures, CFD-er, ETC/ETF-er, aksjer osv."
    )

    inventory_cols = st.columns(3)
    inventory_cols[0].metric("Unike markedstreff", len(inventory.rows))
    inventory_cols[1].metric("AssetTypes funnet", inventory.asset_type_count)
    inventory_cols[2].metric("Søk med treff", sum(1 for item in inventory.queries if item.returned > 0))

    if inventory.account_labels:
        st.caption("Inventar evalueres mot aktiv Saxo-konto: " + ", ".join(inventory.account_labels))

    if inventory.asset_type_counts:
        st.dataframe(
            asset_type_rows_for_ui_v2(inventory),
            use_container_width=True,
            hide_index=True,
            height=min(360, 80 + 35 * min(len(inventory.asset_type_counts), 8)),
        )

    if inventory.rows:
        st.dataframe(
            market_inventory_rows_for_ui_v2(inventory.rows),
            use_container_width=True,
            hide_index=True,
            height=min(620, 110 + 35 * min(len(inventory.rows), 15)),
        )
    else:
        st.warning(
            "Saxo returnerte ingen instrumenter for noen av markedsaliasene, selv uten AssetType-filter. "
            "Da er neste spørsmål selve markedsnavnet/account-access — ikke AutoTrader-filteret."
        )

    with st.expander("Rå markedsalias-søk", expanded=not bool(inventory.rows)):
        st.caption(
            "Hver rad er samme account-aware Saxo instrumentsøk uten AssetTypes-filter. Dette viser om f.eks. Gold, XAU, Oil "
            "eller Brent faktisk gir treff før PG forsøker å klassifisere produktene."
        )
        st.dataframe(
            inventory_query_rows_for_ui_v2(inventory.queries),
            use_container_width=True,
            hide_index=True,
        )

    st.markdown("### 2. AutoTrader-kandidater · etter produktfilter")
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

    if not result.rows:
        if inventory.rows:
            st.warning(
                "Saxo har markedsrelaterte instrumenter på kontoen, men ingen av dem ligger i de strukturerte produktfamiliene "
                "PG foreløpig analyserer som AutoTrader-kandidater. Se AssetType-fordelingen over — den er nå fasiten for "
                "hvilke produktfamilier vi faktisk bør undersøke videre."
            )
        elif result.structured_universe_count == 0:
            st.warning(
                "Kontoen eksponerer heller ingen produkter i de strukturerte produktfamiliene scanneren undersøker."
            )
        if result.cats_universe_count == 0:
            st.info(
                "Ingen CATS-produkter er synlige for kontoen. Den dokumenterte 0-kurtasje Turbo-serien er derfor ikke "
                "tilgjengelig via denne kontoen slik API-et eksponerer den nå."
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
            "produktet. 0 kommisjon betyr bare 0 eksplisitt kurtasje; spread, finansiering, FX og andre produktkostnader kan finnes."
        )

        in_universe = [row for row in result.rows if row.in_pg_universe]
        if not in_universe:
            st.info(
                "PG-universet er foreløpig tomt. Scannerfunn blir aldri automatisk godkjent: limited-loss, ingen åpen "
                "marginforpliktelse og kostnadsprofil må verifiseres før en eksakt UIC/AssetType-identitet tillates."
            )

    with st.expander("Structured/CATS-diagnostikk", expanded=False):
        st.caption(
            "Dette er andre trinn og bruker eksplisitte structured AssetTypes. Det skal ikke lenger tolkes som hele Saxo-markedet."
        )
        if result.diagnostics:
            st.dataframe(
                diagnostic_rows_for_ui_v2(result.diagnostics),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("Ingen structured-søkediagnostikk tilgjengelig.")
