from __future__ import annotations

import streamlit as st

from saxo_low_friction_candidates_v2 import LowFrictionScanResultV2
from saxo_margin_precheck_v2 import (
    MarginPrecheckScanResultV2,
    margin_precheck_rows_for_ui_v2,
    scan_minimum_margin_prechecks_v2,
)
from saxo_provider import configured_client


_LOW_FRICTION_KEY = "autotrader_saxo_low_friction_v2"
_MARGIN_PRECHECK_KEY = "autotrader_saxo_margin_precheck_v2"


def render_margin_precheck_v2() -> None:
    st.subheader("Minimumsordre · margin-precheck")
    st.caption(
        "Read-only Saxo order precheck for minste gyldige BUY og SELL på kandidatene over. "
        "Dette måler faktisk cash-/marginpåvirkning mot kontoens nåværende tilstand; ingen ordre kan sendes fra denne komponenten."
    )

    low_friction = st.session_state.get(_LOW_FRICTION_KEY)
    if not isinstance(low_friction, LowFrictionScanResultV2) or not low_friction.rows:
        st.info("Kjør Product Scanner først. Margin-precheck bruker den siste lavfriksjon-shortlisten.")
        return

    try:
        client = configured_client()
    except Exception as exc:
        st.warning(f"Kunne ikke initialisere Saxo for precheck: {exc}")
        return
    if client is None:
        st.info("Koble til Saxo først.")
        return

    if st.button("Precheck minste BUY + SELL", key="autotrader_margin_precheck_button"):
        with st.spinner("Spør Saxo om cash- og marginbehov for minste gyldige ordre …"):
            st.session_state[_MARGIN_PRECHECK_KEY] = scan_minimum_margin_prechecks_v2(
                client,
                low_friction=low_friction,
            )

    result = st.session_state.get(_MARGIN_PRECHECK_KEY)
    if not isinstance(result, MarginPrecheckScanResultV2):
        return

    cols = st.columns(4)
    cols[0].metric("Produkter prechecket", result.inspected)
    cols[1].metric("BUY OK", sum(1 for row in result.rows if row.buy.ok))
    cols[2].metric("SELL OK", sum(1 for row in result.rows if row.sell.ok))
    cols[3].metric("Feilede sider", result.failed_sides)

    if result.account_label:
        st.caption(f"Precheck evalueres mot aktiv Saxo-konto: {result.account_label}")

    if result.rows:
        st.dataframe(
            margin_precheck_rows_for_ui_v2(result.rows),
            use_container_width=True,
            hide_index=True,
            height=min(680, 110 + 35 * min(len(result.rows), 16)),
        )
        st.caption(
            "Initial-/maintenance-margin er Saxos faktiske precheck-respons for minimumsordren. "
            "Verdiene er konto- og posisjonsavhengige og skal derfor senere re-precheckes umiddelbart før hver OPEN/ADD."
        )
        st.warning(
            "Dette er fortsatt discovery: precheck-resultatet åpner ikke LIVE entry og flytter ikke produktet inn i PG-universet."
        )
