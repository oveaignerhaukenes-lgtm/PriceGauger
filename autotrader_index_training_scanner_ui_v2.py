from __future__ import annotations

import streamlit as st

from saxo_low_friction_candidates_v2 import (
    LowFrictionScanResultV2,
    low_friction_rows_for_ui_v2,
    scan_low_friction_margin_candidates_v2,
)
from saxo_market_inventory_v2 import (
    INDEX_CFD_TRAINING_TERMS,
    SaxoMarketInventoryResultV2,
    market_inventory_rows_for_ui_v2,
    precise_asset_type_rows_for_ui_v2,
    precise_market_rows_v2,
    scan_saxo_market_inventory_v2,
)
from saxo_provider import configured_client


INDEX_CFD_TRAINING_MARKET = "Index CFDs · training"
_INDEX_INVENTORY_KEY = "autotrader_index_training_inventory_v2"
_INDEX_LOW_FRICTION_KEY = "autotrader_index_training_low_friction_v2"


def render_index_training_scanner_v2() -> None:
    st.subheader("Index-CFD-er · treningsunivers")
    st.caption(
        "Kartlegger Saxos dokumenterte Index Tracker-symboler som én produktfamilie, uten at du på forhånd trenger "
        "å velge hvilket marked du kjenner best. Målet er små, spreadprisede CfdOnIndex-posisjoner som PG senere kan "
        "rangere etter faktisk spread, minste størrelse, kostnad og margin. Dette er read-only discovery."
    )

    try:
        client = configured_client()
    except Exception as exc:
        st.warning(f"Kunne ikke initialisere Saxo for indeks-scanner: {exc}")
        return
    if client is None:
        st.info("Koble til Saxo først for å kartlegge indeks-CFD-er.")
        return

    col_a, col_b = st.columns([2, 1])
    col_a.caption(
        "Eksakte Saxo-symboler: " + ", ".join(INDEX_CFD_TRAINING_TERMS)
    )
    max_products = col_b.selectbox(
        "Maks indekskandidater å kostnadsanalysere",
        (10, 14, 20),
        index=1,
        key="autotrader_index_training_limit",
    )

    if st.button("Kartlegg indeks-CFD-er", type="primary", key="autotrader_index_training_scan"):
        with st.spinner("Spør Saxo om Index Tracker-universet på kontoen …"):
            inventory = scan_saxo_market_inventory_v2(
                client,
                market=INDEX_CFD_TRAINING_MARKET,
                max_per_query=25,
            )
            st.session_state[_INDEX_INVENTORY_KEY] = inventory
        with st.spinner("Måler spread, minste størrelse og kostnadsprofil …"):
            st.session_state[_INDEX_LOW_FRICTION_KEY] = scan_low_friction_margin_candidates_v2(
                client,
                inventory=inventory,
                max_products=int(max_products),
            )

    inventory = st.session_state.get(_INDEX_INVENTORY_KEY)
    low_friction = st.session_state.get(_INDEX_LOW_FRICTION_KEY)
    if not isinstance(inventory, SaxoMarketInventoryResultV2) or not isinstance(low_friction, LowFrictionScanResultV2):
        return

    precise_rows = precise_market_rows_v2(inventory)
    index_candidates = tuple(row for row in low_friction.rows if row.asset_type == "CfdOnIndex")

    metrics = st.columns(4)
    metrics[0].metric("Index-symboltreff", len(precise_rows))
    metrics[1].metric("CfdOnIndex", len(index_candidates))
    metrics[2].metric(
        "0 kurtasje LONG+SHORT",
        sum(1 for row in index_candidates if row.zero_commission_both_sides is True),
    )
    metrics[3].metric(
        "Min.size ≤ 0,01",
        sum(
            1
            for row in index_candidates
            if row.minimum_trade_size is not None and row.minimum_trade_size <= 0.0100000001
        ),
    )

    if inventory.account_labels:
        st.caption("Kartlegging evalueres mot aktiv Saxo-konto: " + ", ".join(inventory.account_labels))

    precise_types = precise_asset_type_rows_for_ui_v2(inventory)
    if precise_types:
        with st.expander("AssetTypes i indeksfamilien", expanded=False):
            st.dataframe(precise_types, use_container_width=True, hide_index=True)

    if index_candidates:
        st.markdown("#### Index Tracker-kandidater")
        st.dataframe(
            low_friction_rows_for_ui_v2(index_candidates),
            use_container_width=True,
            hide_index=True,
            height=min(680, 110 + 35 * min(len(index_candidates), 16)),
        )
        st.caption(
            "Rangeringen er foreløpig discovery: 0 eksplisitt kurtasje prioriteres først, deretter lav spread / total kost. "
            "Neste steg er å prechecke et lite shortlist mot faktisk minimumsmargin, ikke alle samtidig."
        )
    elif precise_rows:
        st.warning(
            "Saxo returnerte instrumenter for de dokumenterte indeks-symbolene, men ingen CfdOnIndex-rader kom gjennom "
            "lavfriksjonsfilteret. Se råtreffene under for å finne hvilken AssetType kontoen faktisk eksponerer."
        )
    else:
        st.warning("Ingen av de dokumenterte Index Tracker-symbolene ga account-aware treff på denne Saxo-kontoen.")

    with st.expander("Rå Index Tracker-treff", expanded=False):
        if precise_rows:
            st.dataframe(
                market_inventory_rows_for_ui_v2(precise_rows),
                use_container_width=True,
                hide_index=True,
                height=min(620, 110 + 35 * min(len(precise_rows), 15)),
            )
        else:
            st.info("Ingen råtreff å vise.")
