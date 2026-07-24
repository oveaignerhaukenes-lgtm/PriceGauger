from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import streamlit as st

from saxo_auth import SaxoAuthError, configured_oauth_client
from saxo_auth_ui import handle_saxo_oauth_callback, render_saxo_auth_panel
from saxo_provider import configured_client, configured_instruments, discover_instruments


st.set_page_config(page_title="Saxo OpenAPI · PriceGauger", page_icon="🔐", layout="wide")
handle_saxo_oauth_callback()

st.title("Saxo OpenAPI")
st.caption("OAuth, automatisk tokenfornyelse, instrumentkontroll og synlig feed-forsinkelse")

with st.sidebar:
    render_saxo_auth_panel()


oauth = configured_oauth_client()
if oauth is None:
    st.warning("Legg inn Saxo OAuth-verdiene i Streamlit Secrets eller miljøvariabler før tilkobling.")
    st.code(
        'SAXO_APP_KEY = "..."\n'
        'SAXO_APP_SECRET = "..."\n'
        'SAXO_REDIRECT_URI = "http://localhost:8501/Saxo_OpenAPI"\n'
        'SAXO_ENVIRONMENT = "sim"\n'
        'SAXO_TOKEN_PATH = "data/saxo_tokens_sim.json"',
        language="toml",
    )
    st.info("Redirect-URL-en må være identisk med URL-en som er registrert for SIM-applikasjonen hos Saxo.")
    st.stop()

try:
    auth_status = oauth.status()
except SaxoAuthError as exc:
    st.error(str(exc))
    st.stop()

s1, s2, s3, s4 = st.columns(4)
s1.metric("Miljø", str(auth_status.get("environment", "sim")).upper())
s2.metric("OAuth", "Tilkoblet" if auth_status.get("connected") else "Ikke tilkoblet")
s3.metric("Access-token", f"{max(int(auth_status.get('access_seconds_remaining') or 0) // 60, 0)} min")
s4.metric("Refresh-sesjon", f"{max(int(auth_status.get('refresh_seconds_remaining') or 0) // 60, 0)} min")

if not auth_status.get("connected"):
    st.info("Koble til Saxo fra sidepanelet. Etter innlogging kommer du tilbake til denne siden.")
    st.stop()

client = configured_client()
if client is None:
    st.error("OAuth er tilkoblet, men SaxoClient kunne ikke opprettes.")
    st.stop()

st.subheader("Konfigurerte instrumenter")
instruments = configured_instruments()
if not instruments:
    st.warning("Ingen instrumenter er konfigurert i SAXO_INSTRUMENTS_JSON.")
else:
    rows = []
    for asset, instrument in instruments.items():
        rows.append(
            {
                "Aktivum": asset,
                "UIC": instrument.uic,
                "AssetType": instrument.asset_type,
                "Symbol": instrument.symbol,
                "Beskrivelse": instrument.description,
                "Utløp": instrument.expiry or "—",
            }
        )
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

st.subheader("Feed-diagnostikk")
st.caption("InfoPrices brukes til å vise om prisen er sanntid, forsinket eller indikativ. Dette er separat fra OHLC-chartdataene.")

if instruments:
    selected_asset = st.selectbox("Instrument", list(instruments))
    selected = instruments[selected_asset]
    if st.button("Test Saxo-feed", type="primary", use_container_width=True):
        try:
            payload = client.info_price(selected)
            quote = payload.get("Quote", {}) if isinstance(payload.get("Quote"), dict) else {}
            price_info = payload.get("PriceInfo", {}) if isinstance(payload.get("PriceInfo"), dict) else {}
            delayed = quote.get("DelayedByMinutes")
            bid = quote.get("Bid")
            ask = quote.get("Ask")
            mid = None
            if bid is not None and ask is not None:
                mid = (float(bid) + float(ask)) / 2
            elif bid is not None:
                mid = float(bid)
            elif ask is not None:
                mid = float(ask)

            if delayed is None:
                feed_status = "DELAY_UNKNOWN"
            elif float(delayed) == 0:
                feed_status = "REALTIME"
            else:
                feed_status = f"DELAYED_{int(float(delayed))}MIN"

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Feedstatus", feed_status)
            c2.metric("Forsinkelse", f"{delayed} min" if delayed is not None else "Ukjent")
            c3.metric("Bid / Ask", f"{bid} / {ask}")
            c4.metric("Mid", f"{mid:g}" if mid is not None else "—")
            st.write(
                f"**Prisstatus:** {quote.get('PriceTypeBid') or quote.get('PriceTypeAsk') or price_info.get('PriceStatus') or 'ukjent'}  "
                f"\n**Mottatt:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"
            )
            with st.expander("Rå InfoPrices-respons"):
                st.json(payload)
        except Exception as exc:
            st.error(f"Saxo feed-test feilet: {exc}")

st.subheader("Instrument discovery")
st.caption("Brukes bare for å finne riktige UIC-er. Valg lagres ikke automatisk.")
if st.button("Søk etter Brent, gull, sølv og DXY", use_container_width=True):
    try:
        discovered = discover_instruments(client)
        for asset, candidates in discovered.items():
            with st.expander(f"{asset} · {len(candidates)} treff", expanded=asset == "Brent"):
                st.dataframe(
                    pd.DataFrame(
                        [
                            {
                                "UIC": item.uic,
                                "AssetType": item.asset_type,
                                "Symbol": item.symbol,
                                "Beskrivelse": item.description,
                                "Utløp": item.expiry,
                            }
                            for item in candidates
                        ]
                    ),
                    use_container_width=True,
                    hide_index=True,
                )
    except Exception as exc:
        st.error(f"Instrument discovery feilet: {exc}")
