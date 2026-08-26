from __future__ import annotations

import streamlit as st

from autotrader_product_scanner_v2 import (
    ProductScanResultV2,
    SCANNER_MARKET_SEARCH_TERMS,
    candidate_rows_for_ui_v2,
    diagnostic_rows_for_ui_v2,
    scan_saxo_candidates_v2,
)
from saxo_low_friction_candidates_v2 import (
    LowFrictionScanResultV2,
    low_friction_rows_for_ui_v2,
    scan_low_friction_margin_candidates_v2,
)
from saxo_market_inventory_v2 import (
    SaxoMarketInventoryResultV2,
    asset_type_rows_for_ui_v2,
    broad_recall_rows_v2,
    inventory_query_rows_for_ui_v2,
    market_inventory_rows_for_ui_v2,
    precise_asset_type_rows_for_ui_v2,
    precise_market_rows_v2,
    scan_saxo_market_inventory_v2,
)
from saxo_provider import configured_client


_SCAN_KEY = "autotrader_product_scanner_v2"
_INVENTORY_KEY = "autotrader_saxo_market_inventory_v2"
_LOW_FRICTION_KEY = "autotrader_saxo_low_friction_v2"


def render_product_scanner_v2() -> None:
    st.subheader("AutoTrader Product Scanner")
    st.caption(
        "Read-only kartlegging av Saxo-markedet før PriceGauger filtrerer kandidater. "
        "Først listes alt kontoen kan se for valgt marked uten produktfilter; deretter vurderes lave handelskostnader og risikoprofil."
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
            inventory_now = scan_saxo_market_inventory_v2(
                client,
                market=market,
                max_per_query=250,
            )
            st.session_state[_INVENTORY_KEY] = inventory_now
        with st.spinner(f"Kostnadsanalyserer opptil {limit} presise FX/CFD-kandidater …"):
            st.session_state[_LOW_FRICTION_KEY] = scan_low_friction_margin_candidates_v2(
                client,
                inventory=inventory_now,
                max_products=int(limit),
            )
        with st.spinner(f"Filtrerer og kostnadsanalyserer opptil {limit} strukturerte kandidater …"):
            st.session_state[_SCAN_KEY] = scan_saxo_candidates_v2(
                client,
                market=market,
                max_products=int(limit),
            )

    inventory = st.session_state.get(_INVENTORY_KEY)
    low_friction = st.session_state.get(_LOW_FRICTION_KEY)
    result = st.session_state.get(_SCAN_KEY)
    if (
        not isinstance(inventory, SaxoMarketInventoryResultV2)
        or not isinstance(low_friction, LowFrictionScanResultV2)
        or not isinstance(result, ProductScanResultV2)
    ):
        st.info("Kjør kartleggingen for å se hele Saxo-markedsinventaret før kandidatfiltrering.")
        return

    precise_rows = precise_market_rows_v2(inventory)
    broad_rows = broad_recall_rows_v2(inventory)
    precise_types = precise_asset_type_rows_for_ui_v2(inventory)

    st.markdown("### 1. Saxo-markedsinventar · uten produktfilter")
    st.caption(
        "Saxo-søk er først kjørt helt uten AssetType-filter. Generiske ord som Gold/Oil kan gi store mengder navnetreff, "
        "så PG viser presise markedsaliaser først og beholder bred recall separat under."
    )

    inventory_cols = st.columns(4)
    inventory_cols[0].metric("Presise markedstreff", len(precise_rows))
    inventory_cols[1].metric("AssetTypes presise", len(precise_types))
    inventory_cols[2].metric("Bred recall", len(broad_rows))
    inventory_cols[3].metric("Totale unike treff", len(inventory.rows))

    if inventory.account_labels:
        st.caption("Inventar evalueres mot aktiv Saxo-konto: " + ", ".join(inventory.account_labels))

    if precise_types:
        st.markdown("#### Presis AssetType-fordeling")
        st.dataframe(
            precise_types,
            use_container_width=True,
            hide_index=True,
            height=min(360, 80 + 35 * min(len(precise_types), 8)),
        )

    if precise_rows:
        st.markdown("#### Presise markedsrelaterte treff")
        st.dataframe(
            market_inventory_rows_for_ui_v2(precise_rows),
            use_container_width=True,
            hide_index=True,
            height=min(620, 110 + 35 * min(len(precise_rows), 15)),
        )
        st.caption(
            "Dette er første kandidatgrunnlag videre: treff via markedsnære aliaser som XAU/XAUUSD/Gold Spot eller "
            "Brent/ICE Brent/UKOIL. Ingen suitability eller execution-eligibility er utledet ennå."
        )
    else:
        st.warning("Ingen treff via de presise markedsaliasene. Se bred recall og rå søkediagnostikk under.")

    with st.expander(f"Bred recall / navnetreff ({len(broad_rows)})", expanded=False):
        st.caption(
            "Dette er treff som bare kom via brede ord som Gold, Oil eller Gas. De er nyttige for recall, men kan inneholde "
            "Goldman Sachs, gruveselskaper, oljeselskaper, obligasjoner osv. og brukes derfor ikke som primær shortlist."
        )
        if broad_rows:
            st.dataframe(
                market_inventory_rows_for_ui_v2(broad_rows),
                use_container_width=True,
                hide_index=True,
                height=min(520, 110 + 35 * min(len(broad_rows), 12)),
            )

    with st.expander("Hele AssetType-fordelingen inkl. bred recall", expanded=False):
        if inventory.asset_type_counts:
            st.dataframe(
                asset_type_rows_for_ui_v2(inventory),
                use_container_width=True,
                hide_index=True,
                height=min(420, 80 + 35 * min(len(inventory.asset_type_counts), 10)),
            )

    with st.expander("Rå markedsalias-søk", expanded=False):
        st.caption(
            "Hver rad er samme account-aware Saxo instrumentsøk uten AssetTypes-filter. Et søk som treffer 250 er på "
            "API-grensen for denne scannen og bør tolkes som bred recall, ikke som 250 relevante markedsprodukter."
        )
        st.dataframe(
            inventory_query_rows_for_ui_v2(inventory.queries),
            use_container_width=True,
            hide_index=True,
        )

    st.markdown("### 2. Lavfriksjon / margin-kandidater")
    st.caption(
        "PG undersøker nå presise FxSpot- og CFD-treff selv om de bruker margin. Målet er å finne produkter der inn/ut-kostnaden "
        "primært er spread og der små posisjoner er praktisk mulige. Dette er fortsatt read-only discovery."
    )
    lf_cols = st.columns(4)
    lf_cols[0].metric("Marginfamilier funnet", low_friction.candidate_rows_seen)
    lf_cols[1].metric("Kostnadsanalysert", low_friction.inspected)
    lf_cols[2].metric(
        "0 kurtasje LONG+SHORT",
        sum(1 for row in low_friction.rows if row.zero_commission_both_sides is True),
    )
    lf_cols[3].metric("LIVE eligible", sum(1 for row in low_friction.rows if row.live_execution_eligible))

    st.info(
        "Utviklingsantakelse: kontoen behandles som retail/ESMA med negativ-saldo-beskyttelse mens vi kartlegger kostnader. "
        "Denne antakelsen åpner marginprodukter i scanneren, men åpner ikke LIVE execution. Kontostatus/beskyttelse må "
        "bekreftes før et marginprodukt kan flyttes inn i PGs execution-univers."
    )

    if low_friction.rows:
        st.dataframe(
            low_friction_rows_for_ui_v2(low_friction.rows),
            use_container_width=True,
            hide_index=True,
            height=min(680, 110 + 35 * min(len(low_friction.rows), 16)),
        )
        st.caption(
            "* Kurtasje/Total kost hentes fra Saxos read-only pre-trade cost illustration når endpointet støtter produktet. "
            "Total kost kan også inkludere andre kostnadskomponenter ved den valgte 1-dags illustrasjonen. Spread vises separat."
        )
    else:
        st.warning(
            "Ingen presise FxSpot/CfdOnFutures/CfdOnIndex-treff ble funnet i dette markedet. "
            "AssetType-tabellen over viser hvilke andre familier som faktisk finnes."
        )

    st.markdown("### 3. Strukturerte AutoTrader-kandidater")
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
                "PG foreløpig analyserer som AutoTrader-kandidater. Det er ikke lenger en blocker: margin/FX/CFD-sporet over "
                "undersøkes separat etter faktisk kostnad."
            )
        elif result.structured_universe_count == 0:
            st.warning("Kontoen eksponerer heller ingen produkter i de strukturerte produktfamiliene scanneren undersøker.")
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
                "PG-universet er foreløpig tomt. Scannerfunn blir aldri automatisk godkjent: kostnads- og risikoprofil må "
                "verifiseres før en eksakt UIC/AssetType-identitet tillates."
            )

    with st.expander("Structured/CATS-diagnostikk", expanded=False):
        st.caption(
            "Dette er tredje trinn og bruker eksplisitte structured AssetTypes. Det skal ikke tolkes som hele Saxo-markedet."
        )
        if result.diagnostics:
            st.dataframe(
                diagnostic_rows_for_ui_v2(result.diagnostics),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("Ingen structured-søkediagnostikk tilgjengelig.")
