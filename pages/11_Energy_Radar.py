from __future__ import annotations

import pandas as pd
import streamlit as st

from energy_radar_v1 import rows_v1, scan_brent_market_v1
from saxo_provider import configured_client


st.title("Energy Radar")
st.caption("Olje som makro- og regimesignal · Brent / UKOIL · read-only")
st.info("Energy Radar observerer og forklarer energimarkedet. Den har ingen execution-authority og sender ingen ordre til Saxo.")

st.markdown("### Brent / UKOIL feed")
st.write("Radar oppdager Saxo-produktene på nytt og viser eksplisitt om prisdata er realtime eller forsinket. UKOIL foretrekkes når den er tilgjengelig, men delay skjules aldri.")

if st.button("Oppdater Energy Radar", type="primary", use_container_width=True):
    client = configured_client()
    if client is None:
        st.error("Saxo er ikke konfigurert i denne runtime-en.")
    else:
        with st.spinner("Søker UKOIL/Brent og kontrollerer Saxo-entitlement …"):
            st.session_state["energy_radar_snapshot"] = scan_brent_market_v1(client)

snapshot = st.session_state.get("energy_radar_snapshot")
if snapshot is None:
    st.caption("Trykk Oppdater for å gjøre en read-only Saxo-scan. Ingen kontinuerlig polling kjøres fra siden.")
else:
    preferred = snapshot.preferred
    if preferred is None:
        st.warning("Fant ingen lesbare Brent/UKOIL-kandidater i Saxo-søket.")
    else:
        a, b, c, d = st.columns(4)
        a.metric("Valgt feed", preferred.symbol or "—")
        b.metric("Mid", f"{preferred.mid:.3f}" if preferred.mid is not None else "—")
        c.metric("Delay", f"{preferred.delay_minutes} min" if preferred.delay_minutes is not None else "ukjent")
        d.metric("Asset type", preferred.asset_type)
        if preferred.realtime:
            st.success("Saxo rapporterer realtime prisdata for valgt feed.")
        elif preferred.delay_minutes is not None:
            st.warning(f"Valgt feed er {preferred.delay_minutes} minutter forsinket. Den skal ikke behandles som realtime i senere signalbruk.")
        else:
            st.warning("Delay-status kunne ikke verifiseres. Feed behandles som ukjent, ikke realtime.")

    frame = pd.DataFrame(rows_v1(snapshot))
    if not frame.empty:
        st.dataframe(frame, use_container_width=True, hide_index=True)
    st.caption(f"Sist observert: {snapshot.observed_at:%Y-%m-%d %H:%M:%S} UTC")

st.divider()
st.markdown("### Hva Energy Radar skal forklare")
left, middle, right = st.columns(3)
left.markdown("**Supply**\n\nOPEC+ · produksjon · raffineri · lager/SPR · rørledninger")
middle.markdown("**Transport / geopolitikk**\n\nHormuz · Red Sea · tankere · sanksjoner · krig · forsikring/frakt")
right.markdown("**Etterspørsel / makro**\n\nvekst · USD · renter · Kina · inflasjon · resesjonsprising")

st.markdown("### Tolkningskjede")
st.code("hendelse → fysisk/forventet tilbud-etterspørsel → lager/frakt/risk premium → oljepris → inflasjon/renter → gull/aksjer", language=None)
st.caption("Neste lag kan koble inn hendelsesdata og retrospektive snapshots. Selve oljeprisen er nå eksplisitt provider-/delay-kontrollert i stedet for å anta at en Brent future er realtime.")
