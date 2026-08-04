from __future__ import annotations

from datetime import datetime

import streamlit as st

from build_info import render_build_badge
from saxo_auth import SaxoAuthError, configured_oauth_client
from saxo_provider import configured_client, configured_instruments


st.set_page_config(page_title="Saxo · PriceGauger", page_icon="🔌", layout="wide")
render_build_badge()
st.title("Saxo")
st.caption("Tilkobling, tokenstatus og manuell kontroll av prisgrunnlaget. Ingen ordreutførelse.")

oauth = configured_oauth_client()
if oauth is None:
    st.error("Saxo OAuth er ikke konfigurert.")
    st.code("SAXO_APP_KEY\nSAXO_APP_SECRET\nSAXO_REDIRECT_URI\nSAXO_ENVIRONMENT=sim")
    st.stop()

try:
    status = oauth.status()
except Exception as exc:
    st.error(f"Kunne ikke lese Saxo-status: {exc}")
    st.stop()

connected = bool(status.get("connected"))
environment = str(status.get("environment") or "ukjent").upper()
c1, c2, c3 = st.columns(3)
c1.metric("Tilkobling", "Tilkoblet" if connected else "Ikke tilkoblet")
c2.metric("Miljø", environment)
remaining = status.get("access_seconds_remaining")
c3.metric("Access-token", f"{max(int(remaining or 0), 0) // 60} min" if connected else "—")

if status.get("refresh_expires_at"):
    try:
        refresh_expiry = datetime.fromisoformat(str(status["refresh_expires_at"]).replace("Z", "+00:00"))
        st.caption(f"Refresh-token utløper {refresh_expiry:%d.%m.%Y %H:%M %Z}")
    except ValueError:
        pass

params = st.query_params
code = str(params.get("code") or "")
returned_state = str(params.get("state") or "")
expected_state = st.session_state.get("saxo_oauth_state")
if code:
    if not expected_state or returned_state != expected_state:
        st.error("OAuth-returen hadde ugyldig state. Start innloggingen på nytt.")
    else:
        try:
            oauth.exchange_code(code)
            st.session_state.pop("saxo_oauth_state", None)
            st.query_params.clear()
            st.success("Saxo er koblet til.")
            st.rerun()
        except SaxoAuthError as exc:
            st.error(str(exc))

if not connected:
    url, state = oauth.build_authorization_url()
    st.session_state["saxo_oauth_state"] = state
    st.link_button("Koble til Saxo", url, type="primary", use_container_width=True)
else:
    left, right = st.columns(2)
    with left:
        if st.button("Forny token nå", use_container_width=True):
            try:
                oauth.refresh()
                st.success("Token er fornyet.")
                st.rerun()
            except SaxoAuthError as exc:
                st.error(str(exc))
    with right:
        if st.button("Koble fra", use_container_width=True):
            oauth.disconnect()
            st.success("Lokale Saxo-token er fjernet.")
            st.rerun()

st.subheader("Konfigurerte instrumenter")
instruments = configured_instruments()
if not instruments:
    st.warning("Ingen instrumenter er konfigurert i SAXO_INSTRUMENTS_JSON.")
else:
    st.dataframe(
        [
            {
                "marked": item.asset,
                "symbol": item.symbol,
                "UIC": item.uic,
                "type": item.asset_type,
                "utløp": item.expiry or "løpende",
            }
            for item in instruments.values()
        ],
        hide_index=True,
        use_container_width=True,
    )

st.subheader("Manuell pristest")
st.caption("Denne testen gjør et eksplisitt kall mot Saxo og kjøres ikke automatisk ved sideåpning.")
if not connected:
    st.info("Koble til Saxo før pristesten kjøres.")
elif not instruments:
    st.info("Konfigurer minst ett instrument før pristesten kjøres.")
else:
    selected = st.selectbox("Instrument", list(instruments))
    if st.button("Test prisrettigheter", type="primary", use_container_width=True):
        try:
            client = configured_client()
            if client is None:
                raise RuntimeError("Saxo-klienten kunne ikke opprettes.")
            instrument = instruments[selected]
            frame = client.chart(instrument, horizon_minutes=5, count=2)
            if frame.empty:
                st.warning("Saxo svarte, men returnerte ingen prisbarer.")
            else:
                latest = frame.iloc[-1]
                st.success(
                    f"Prisdata mottatt: {selected} {float(latest['close']):,.3f} · "
                    f"{latest['timestamp']}"
                )
        except Exception as exc:
            st.error(f"Pristesten feilet: {exc}")
