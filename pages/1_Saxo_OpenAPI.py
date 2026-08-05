from __future__ import annotations

import streamlit as st

from build_info import render_build_badge
from saxo_auth import configured_oauth_client
from saxo_auth_ui import handle_saxo_oauth_callback, render_saxo_auth_panel
from saxo_diagnostics import diagnose_info_price
from saxo_provider import configured_client, configured_instruments, instrument_is_unexpired


st.set_page_config(page_title="Saxo · PriceGauger", page_icon="🔌", layout="wide")
render_build_badge()
handle_saxo_oauth_callback()

st.title("Saxo OpenAPI")
st.caption("Tilkobling, tokenstatus, instrumentoppsett og kontroll av prisrettigheter.")

render_saxo_auth_panel()

try:
    oauth = configured_oauth_client()
    oauth_status = oauth.status() if oauth is not None else None
except Exception as exc:
    oauth_status = None
    st.error(f"Kunne ikke lese Saxo-tokenstatus: {exc}")

environment = str((oauth_status or {}).get("environment", "sim")).upper()
connected = bool((oauth_status or {}).get("connected"))
try:
    configured = configured_instruments()
except (TypeError, ValueError) as exc:
    configured = {}
    st.error(f"SAXO_INSTRUMENTS_JSON er ugyldig: {exc}")

c1, c2, c3 = st.columns(3)
c1.metric("Miljø", environment)
c2.metric("OAuth", "Tilkoblet" if connected else "Ikke tilkoblet")
c3.metric("Instrumenter", len(configured))

st.subheader("Konfigurerte instrumenter")
if not configured:
    st.warning("Ingen instrumenter er konfigurert i SAXO_INSTRUMENTS_JSON.")
else:
    st.dataframe(
        [
            {
                "Marked": asset,
                "Symbol": instrument.symbol or "—",
                "UIC": instrument.uic,
                "Type": instrument.asset_type,
                "Utløp": instrument.expiry or "—",
                "Gyldig": "Ja" if instrument_is_unexpired(instrument) else "Nei",
            }
            for asset, instrument in configured.items()
        ],
        use_container_width=True,
        hide_index=True,
    )

st.subheader("Prisdiagnostikk")
st.caption("Kjøres bare når du trykker på knappen. Den legger ikke inn ordre og endrer ingen Saxo-data.")
if st.button("Test tilkobling og prisrettigheter", type="primary", disabled=not connected or not configured):
    client = configured_client()
    if client is None:
        st.error("Saxo-klienten er ikke konfigurert.")
    else:
        rows = []
        for asset, instrument in configured.items():
            try:
                diagnostic = diagnose_info_price(client.info_price(instrument))
                rows.append(
                    {
                        "Marked": asset,
                        "Status": diagnostic.status,
                        "Mid": diagnostic.mid,
                        "Forsinkelse (min)": diagnostic.delay_minutes,
                        "Forklaring": diagnostic.explanation,
                    }
                )
            except Exception as exc:
                rows.append({"Marked": asset, "Status": "FEIL", "Forklaring": str(exc)})
        st.dataframe(rows, use_container_width=True, hide_index=True)
