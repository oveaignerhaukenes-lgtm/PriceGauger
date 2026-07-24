from __future__ import annotations

from datetime import datetime, timezone
from time import perf_counter

import pandas as pd
import streamlit as st

from saxo_auth import SaxoAuthError, configured_oauth_client
from saxo_auth_ui import handle_saxo_oauth_callback, render_saxo_auth_panel
from saxo_diagnostics import diagnose_chart, diagnose_info_price
from saxo_provider import configured_client, configured_instruments, discover_instruments


st.set_page_config(page_title="Saxo OpenAPI · PriceGauger", page_icon="🔐", layout="wide")
handle_saxo_oauth_callback()

st.title("Saxo OpenAPI")
st.caption("OAuth, automatisk tokenfornyelse, instrumentkontroll og synlig feed-forsinkelse")

with st.sidebar:
    render_saxo_auth_panel()


def _status_icon(status: str) -> str:
    if status in {"REALTIME", "CHART_AVAILABLE", "CONNECTED"}:
        return "🟢"
    if status.startswith("DELAYED_") or status in {"PRICE_AVAILABLE_DELAY_UNKNOWN", "NO_BARS"}:
        return "🟡"
    return "🔴"


def _run_instrument_diagnostic(asset: str, instrument) -> dict:
    received_at = datetime.now(timezone.utc)
    row = {
        "Aktivum": asset,
        "Symbol": instrument.symbol or "—",
        "UIC": instrument.uic,
        "InfoPrices": "IKKE TESTET",
        "Forsinkelse": None,
        "Prisstatus": "—",
        "Mid": None,
        "Chart": "IKKE TESTET",
        "Prisbarer": 0,
        "Siste bar": None,
        "Responstid ms": None,
        "Forklaring": "",
        "Rå respons": None,
    }

    started = perf_counter()
    try:
        payload = client.info_price(instrument)
        info = diagnose_info_price(payload)
        row.update(
            {
                "InfoPrices": info.status,
                "Forsinkelse": info.delay_minutes,
                "Prisstatus": info.price_status,
                "Mid": info.mid,
                "Forklaring": info.explanation,
                "Rå respons": payload,
            }
        )
    except Exception as exc:
        row["InfoPrices"] = getattr(exc, "status", "REQUEST_FAILED")
        row["Forklaring"] = str(exc)

    try:
        frame = client.chart(instrument, horizon_minutes=5, count=24)
        chart = diagnose_chart(frame, now=pd.Timestamp(received_at))
        row.update(
            {
                "Chart": chart.status,
                "Prisbarer": chart.bars,
                "Siste bar": chart.last_timestamp,
                "Siste close": chart.last_close,
            }
        )
        if row["Forklaring"]:
            row["Forklaring"] += " " + chart.explanation
        else:
            row["Forklaring"] = chart.explanation
    except Exception as exc:
        row["Chart"] = getattr(exc, "status", "REQUEST_FAILED")
        row["Forklaring"] += f" Chart: {exc}"

    row["Responstid ms"] = round((perf_counter() - started) * 1000, 1)
    row["Mottatt"] = received_at.isoformat()
    return row


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

st.subheader("Saxo Diagnostics Dashboard")
st.caption(
    "Tester autentisering, InfoPrices og 5-minutters chartdata separat. "
    "NoAccess betyr at API-et og instrumentet fungerer, men at SIM-kontoen mangler prisrettighet."
)

if instruments:
    if st.button("Kjør full diagnostikk for alle instrumenter", type="primary", use_container_width=True):
        with st.spinner("Tester Saxo-endepunktene …"):
            st.session_state["saxo_diagnostics"] = [
                _run_instrument_diagnostic(asset, instrument) for asset, instrument in instruments.items()
            ]

    diagnostic_rows = st.session_state.get("saxo_diagnostics", [])
    if diagnostic_rows:
        overview = []
        for row in diagnostic_rows:
            overview.append(
                {
                    "Aktivum": row["Aktivum"],
                    "InfoPrices": f"{_status_icon(row['InfoPrices'])} {row['InfoPrices']}",
                    "Forsinkelse": f"{row['Forsinkelse']:g} min" if row.get("Forsinkelse") is not None else "Ukjent",
                    "Prisstatus": row["Prisstatus"],
                    "Mid": row.get("Mid"),
                    "Chart": f"{_status_icon(row['Chart'])} {row['Chart']}",
                    "Prisbarer": row["Prisbarer"],
                    "Siste bar": row.get("Siste bar") or "—",
                    "Responstid": f"{row['Responstid ms']:.1f} ms",
                }
            )
        st.dataframe(pd.DataFrame(overview), use_container_width=True, hide_index=True)

        for row in diagnostic_rows:
            with st.expander(f"{row['Aktivum']} · {row['InfoPrices']} · {row['Chart']}"):
                st.write(row["Forklaring"])
                details = {
                    key: value
                    for key, value in row.items()
                    if key not in {"Rå respons", "Forklaring"}
                }
                st.json(details)
                if row.get("Rå respons") is not None:
                    st.markdown("**Rå InfoPrices-respons**")
                    st.json(row["Rå respons"])

st.subheader("Enkeltinstrument")
st.caption("Bruk dette for detaljert kontroll av ett instrument og den rå Saxo-responsen.")

if instruments:
    selected_asset = st.selectbox("Instrument", list(instruments))
    selected = instruments[selected_asset]
    if st.button("Test valgt Saxo-feed", use_container_width=True):
        with st.spinner(f"Tester {selected_asset} …"):
            row = _run_instrument_diagnostic(selected_asset, selected)
        info_status = row["InfoPrices"]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Feedstatus", info_status)
        c2.metric("Forsinkelse", f"{row['Forsinkelse']:g} min" if row.get("Forsinkelse") is not None else "Ukjent")
        c3.metric("Prisstatus", row["Prisstatus"])
        c4.metric("Mid", f"{row['Mid']:g}" if row.get("Mid") is not None else "—")

        d1, d2, d3, d4 = st.columns(4)
        d1.metric("Chart", row["Chart"])
        d2.metric("Prisbarer", row["Prisbarer"])
        d3.metric("Siste close", f"{row['Siste close']:g}" if row.get("Siste close") is not None else "—")
        d4.metric("Responstid", f"{row['Responstid ms']:.1f} ms")

        if info_status == "NO_ACCESS":
            st.error(row["Forklaring"])
        elif info_status.startswith("DELAYED_"):
            st.warning(row["Forklaring"])
        else:
            st.info(row["Forklaring"])

        with st.expander("Rå InfoPrices-respons"):
            st.json(row.get("Rå respons") or {})

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
