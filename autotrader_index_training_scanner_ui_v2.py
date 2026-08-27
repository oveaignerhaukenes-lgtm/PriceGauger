from __future__ import annotations

import streamlit as st

from saxo_low_friction_candidates_v2 import (
    LowFrictionScanResultV2,
    low_friction_rows_for_ui_v2,
    scan_low_friction_margin_candidates_v2,
)
from saxo_margin_precheck_v2 import (
    FRACTIONAL_PROBE_AMOUNTS_V2,
    FractionalMarginProbeCandidateV2,
    FractionalMarginProbeResultV2,
    fractional_margin_probe_rows_for_ui_v2,
    scan_fractional_margin_probe_v2,
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
_INDEX_MARGIN_PROBE_KEY = "product_browser_index_fractional_margin_probe_v2"


def _matches_profile(
    row: FractionalMarginProbeCandidateV2,
    *,
    max_initial_margin: float,
    max_spread_pct: float,
    require_zero_commission: bool,
) -> bool:
    if not row.both_sides_ok:
        return False
    if row.max_initial_margin is None or row.max_initial_margin > max_initial_margin:
        return False
    if row.spread_pct is None or row.spread_pct * 100.0 > max_spread_pct:
        return False
    if require_zero_commission and row.zero_commission_both_sides is not True:
        return False
    return True


def render_index_training_scanner_v2() -> None:
    st.subheader("Index-CFD-er · treningsunivers")
    st.caption(
        "Kartlegger Saxos dokumenterte Index Tracker-symboler som én execution-familie uten at du på forhånd trenger "
        "å velge marked. Produktnavn/AssetType er sekundært; browseren rangerer etter spread, kurtasje, minste praktiske "
        "posisjon og faktisk margin. Dette er read-only discovery."
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
    col_a.caption("Eksakte Saxo-symboler: " + ", ".join(INDEX_CFD_TRAINING_TERMS))
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
        st.session_state.pop(_INDEX_MARGIN_PROBE_KEY, None)

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
        "API oppgir min.size ≤ 0,01",
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
            "Første rangering: 0 eksplisitt kurtasje, deretter lav spread / total kost. Saxo instrument-details kan la "
            "MinimumTradeSize stå tomt selv når 0,01 faktisk er gyldig; derfor bruker neste trinn ordre-precheck som fasit."
        )
    elif precise_rows:
        st.warning(
            "Saxo returnerte instrumenter for de dokumenterte indeks-symbolene, men ingen CfdOnIndex-rader kom gjennom "
            "lavfriksjonsfilteret. Se råtreffene under for å finne hvilken AssetType kontoen faktisk eksponerer."
        )
    else:
        st.warning("Ingen av de dokumenterte Index Tracker-symbolene ga account-aware treff på denne Saxo-kontoen.")

    if index_candidates:
        st.markdown("#### Egenskapsbasert shortlist · faktisk margin")
        st.caption(
            "Browseren prøver et lite eksplisitt størrelsestrinn mot Saxos read-only precheck og finner den minste av "
            f"{', '.join(f'{value:g}' for value in FRACTIONAL_PROBE_AMOUNTS_V2)} kontrakt som fungerer både LONG og SHORT. "
            "Det er minste testede størrelse som fungerer nå — ikke en påstand om Saxos kontraktsmessige minimum."
        )

        probe_control, profile_margin, profile_spread = st.columns([1.1, 1, 1])
        shortlist_size = probe_control.selectbox(
            "Kandidater å prechecke",
            (3, 5, 8),
            index=1,
            key="product_browser_index_probe_limit",
            help="Hold shortlisten liten: hver kandidat kan kreve flere read-only precheck-kall.",
        )
        max_margin = profile_margin.number_input(
            "Maks initial margin",
            min_value=50.0,
            value=1000.0,
            step=250.0,
            key="product_browser_index_max_margin",
            help="Kontoens marginvaluta vises i resultatet. Dette er et browserfilter, ikke AutoTrader-risikogrensen.",
        )
        max_spread = profile_spread.number_input(
            "Maks spread %",
            min_value=0.0,
            value=0.05,
            step=0.005,
            format="%.4f",
            key="product_browser_index_max_spread",
        )
        require_zero = st.checkbox(
            "Krev 0 eksplisitt kurtasje LONG + SHORT",
            value=True,
            key="product_browser_index_require_zero_commission",
        )

        if st.button(
            "Probe minste størrelse og ranger på egenskaper",
            type="primary",
            key="product_browser_index_fractional_probe",
        ):
            with st.spinner("Prechecker en liten shortlist sekvensielt for å respektere Saxo rate limits …"):
                st.session_state[_INDEX_MARGIN_PROBE_KEY] = scan_fractional_margin_probe_v2(
                    client,
                    candidates=index_candidates,
                    max_candidates=int(shortlist_size),
                    amount_ladder=FRACTIONAL_PROBE_AMOUNTS_V2,
                    pause_seconds=0.35,
                )

        probe = st.session_state.get(_INDEX_MARGIN_PROBE_KEY)
        if isinstance(probe, FractionalMarginProbeResultV2):
            matches = tuple(
                row
                for row in probe.rows
                if _matches_profile(
                    row,
                    max_initial_margin=float(max_margin),
                    max_spread_pct=float(max_spread),
                    require_zero_commission=bool(require_zero),
                )
            )
            probe_metrics = st.columns(4)
            probe_metrics[0].metric("Prechecket", probe.inspected)
            probe_metrics[1].metric("LONG + SHORT OK", sum(1 for row in probe.rows if row.both_sides_ok))
            probe_metrics[2].metric("Passer profil", len(matches))
            probe_metrics[3].metric("Precheck-kall", probe.precheck_calls)

            if probe.account_label:
                st.caption(f"Margin/precheck evalueres mot aktiv Saxo-konto: {probe.account_label}")

            if matches:
                st.success(
                    "Produktene under tilfredsstiller den valgte finansielle profilen. De er sortert etter faktisk "
                    "maks initial margin først, deretter spread — ikke alfabetisk eller etter produkttype."
                )
                st.dataframe(
                    fractional_margin_probe_rows_for_ui_v2(matches),
                    use_container_width=True,
                    hide_index=True,
                    height=min(500, 110 + 35 * min(len(matches), 10)),
                )
            else:
                st.warning(
                    "Ingen precheckede produkter tilfredsstiller alle profilkravene. Tabellen under viser hele den testede "
                    "shortlisten, fortsatt rangert etter execution-egenskaper."
                )
                st.dataframe(
                    fractional_margin_probe_rows_for_ui_v2(probe.rows),
                    use_container_width=True,
                    hide_index=True,
                    height=min(500, 110 + 35 * min(len(probe.rows), 10)),
                )

            st.caption(
                "Dette flytter ingen instrumenter til PG Product Universe og gir ingen LIVE execution-authority. "
                "Margin er konto-/posisjonsavhengig og må re-precheckes umiddelbart før fremtidig OPEN/ADD."
            )

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
