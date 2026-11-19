from __future__ import annotations

from datetime import datetime
import json

import streamlit as st

from build_info import render_build_badge
from saxo_auth import SaxoAuthError, configured_oauth_client
from saxo_auth_ui import handle_saxo_oauth_callback, render_saxo_auth_panel
from saxo_oauth_diagnostics import safe_oauth_runtime_preflight
from saxo_discover import discover_pricegauger_instruments
from saxo_provider import (
    configured_client,
    configured_instruments,
    instrument_config_payload,
    instrument_is_unexpired,
    latest_gold_silver_ratio,
)
from saxo_rest_quota_dashboard_v1 import (
    load_saxo_rest_usage_v1,
    summarize_saxo_rest_usage_v1,
)


st.set_page_config(page_title="Saxo · PriceGauger", page_icon="🔌", layout="wide")
render_build_badge()
st.title("Saxo")
st.caption("Tilkobling, tokenstatus og manuell kontroll av prisgrunnlaget. Ingen ordreutførelse.")

# Saxo redirects to /Saxo_OpenAPI?code=...&state=.... Consume the
# callback before reading status so the freshly issued token is visible below.
handle_saxo_oauth_callback()

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

with st.expander("OAuth-diagnose: faktisk konfigurasjon (uten hemmeligheter)", expanded=False):
    diagnostic = safe_oauth_runtime_preflight(oauth.config)
    st.json(diagnostic, expanded=True)
    st.caption(
        "Leses kun fra kjørende tjeneste. Sammenlign AppKey-suffiks og "
        "SHA-256-fingeravtrykk mot Saxo LIVE-appen. "
        "Ingen apphemmeligheter, tokenverdier eller autorisasjonskoder vises."
    )
    if not diagnostic["auth_endpoint_matches_environment"] or diagnostic["client_id_contains_quotes_or_controls"]:
        st.warning("OAuth-konfigurasjonen har et mulig avvik. Kontroller Railway-variablene.")
    if diagnostic["redirect_contains_query"]:
        st.warning("Redirect-URL inneholder query eller fragment. Sammenlign med Saxo-appens registrerte URL.")

if status.get("refresh_expires_at"):
    try:
        refresh_expiry = datetime.fromisoformat(str(status["refresh_expires_at"]).replace("Z", "+00:00"))
        st.caption(f"Refresh-token utløper {refresh_expiry:%d.%m.%Y %H:%M %Z}")
    except ValueError:
        pass

if not connected:
    render_saxo_auth_panel()
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
            st.success("Saxo-token er fjernet fra det delte lageret.")
            st.rerun()

st.subheader("Saxo API · REST-kall og kvoter")
st.caption(
    "Måles uten ekstra Saxo-kall. Dette er REST-kall observert av PriceGauger LIVE-worker, "
    "ikke et komplett regnskap over alle Saxo-apper eller sesjoner. "
    "Web-panelet leser bare lagrede tellere, normalt med rundt 1–2 minutters forsinkelse."
)
period = st.selectbox(
    "Statistikkperiode", [15, 60, 360, 1440], index=1,
    format_func=lambda minutes: {
        15: "15 minutter", 60: "1 time", 360: "6 timer", 1440: "24 timer",
    }[minutes],
    key="saxo_rest_usage_minutes",
)
try:
    usage = summarize_saxo_rest_usage_v1(load_saxo_rest_usage_v1(minutes=period))
except Exception as exc:
    st.warning(
        "Klarte ikke å lese REST-statistikk fra databasen. "
        f"Feilkategori: {type(exc).__name__}."
    )
    usage = summarize_saxo_rest_usage_v1(())
api_total, api_limited, api_peak = st.columns(3)
api_total.metric("Observerte REST-kall", f"{usage['calls']:,}".replace(",", " "))
api_limited.metric("HTTP 429", usage["http429"])
peak = max((bucket["calls"] for bucket in usage["minutes"]), default=0)
api_peak.metric("Høyeste rapporterte intervall", peak)

if usage["calls"]:
    st.caption(
        "Sist rapporterte vindu (UTC): "
        + max(bucket["minute"] for bucket in usage["minutes"])
        + ". Intervallene er normalt 60 sekunder under aktiv handel. "
        "Antall per vindu måler faktiske HTTP-forsøk; det er ikke en "
        "glidende, Saxo-autoritativ minuttkvote."
    )
    st.markdown("**Kall per type og endepunkt**")
    st.dataframe(
        [
            {
                "Metode": row["method"], "Endepunkt": row["endpoint"],
                "Antall": row["calls"], "HTTP 429": row["http429"],
            }
            for row in usage["endpoints"]
        ],
        hide_index=True, use_container_width=True,
    )
    with st.expander("Tidsserie · rapporterte 60s-vinduer"):
        st.dataframe(
            [
                {"UTC": row["minute"], "REST-kall": row["calls"], "HTTP 429": row["http429"]}
                for row in usage["minutes"]
            ],
            hide_index=True, use_container_width=True,
        )
else:
    st.info(
        "Ingen lagrede LIVE-REST-kall i perioden ennå. "
        "Tellere vises når worker har rapportert og sideprosessen kan lese felles database."
    )

st.markdown("**Saxos kvoteheadere · siste observerte svar**")
quota_labels = {
    "appday": "AppDay · applikasjon/døgn",
    "session": "Session · sesjon/tjenestegruppe/minutt",
    "sessionorders": "SessionOrders · sesjon/ordre/sekund",
}
if usage["quotas"]:
    st.dataframe(
        [
            {
                "Kvotetype": quota_labels.get(row["dimension"], row["dimension"]),
                "Grense": row["limit"], "Gjenstår": row["remaining"],
                "Brukt (%)": row["used_pct"],
                "Til reset (sek)": row["reset_seconds"] if row["reset_seconds"] is not None else "—",
                "Målt fra": row["source"], "Vindu (UTC)": row["sampled_at"][:19],
            }
            for row in usage["quotas"]
        ],
        hide_index=True, use_container_width=True,
    )
    st.caption(
        "Prosentene kommer fra Saxos Limit/Remaining-headere, ikke fra våre lokale summer. "
        "Sesjonskvotene gjelder bare den sesjonen/tjenestegruppen som leverte svaret; "
        "de kan ikke summeres som én felles seks-instanskvote. "
        "Reset-verdier er fra prøvetidspunktet, ikke en nåværende nedtelling."
    )
else:
    st.caption(
        "Ingen komplette Limit/Remaining-headere observert i perioden. "
        "Viser ingen anslått kvoteprosent uten Saxos faktiske tall."
    )
st.caption(
    "Saxos dokumenterte standardgrenser: 10 millioner per applikasjon/døgn, "
    "120 per sesjon/tjenestegruppe/minutt og én ordre per sesjon/sekund. "
    "Ingen generell timekvote er oppgitt. Faktiske kvoter kan avvike per applikasjon."
)

st.subheader("Finn Saxo-instrumenter")
st.caption(
    "Søk gjøres bare når du trykker på knappen. Kontroller symbol, beskrivelse, type og utløp før JSON-en brukes."
)
if not connected:
    st.info("Koble til Saxo før instrumentsøket kjøres.")
elif st.button("Søk etter Brent, gull, sølv, DXY, Natural Gas og US 10Y", use_container_width=True):
    try:
        discovery_client = configured_client()
        if discovery_client is None:
            raise RuntimeError("Saxo-klienten kunne ikke opprettes.")
        with st.spinner("Søker i Saxos instrumentkatalog …"):
            st.session_state["saxo_discovered_instruments"] = discover_pricegauger_instruments(discovery_client)
    except Exception as exc:
        st.error(f"Instrumentsøket feilet: {exc}")

discovered = st.session_state.get("saxo_discovered_instruments", {})
selected_discovered = {}
selected_multipliers = {}
if discovered:
    st.warning(
        "US10Y kan være en 10-årig Treasury-future. Futuresprisen går normalt motsatt av yielden; "
        "bruk den ikke som om tallet var selve 10-årsrenten."
    )
    for asset, candidates in discovered.items():
        valid = [item for item in candidates if instrument_is_unexpired(item)]
        if not valid:
            st.warning(f"Ingen gyldige kandidater funnet for {asset}.")
            continue
        labels = {
            f"{item.symbol or 'uten symbol'} · {item.description or 'uten beskrivelse'} · "
            f"{item.asset_type} · utløp {item.expiry or 'løpende'} · UIC {item.uic}": item
            for item in valid[:20]
        }
        label = st.selectbox(f"{asset}-kandidat", list(labels), key=f"saxo_candidate_{asset}")
        selected_discovered[asset] = labels[label]
        selected_multipliers[asset] = st.number_input(
            f"Prismultiplikator · {asset}",
            min_value=0.000001,
            value=0.01 if asset == "Silver" else 1.0,
            format="%.6f",
            key=f"saxo_multiplier_{asset}",
        )

    if selected_discovered:
        generated = instrument_config_payload(
            selected_discovered,
            price_multipliers=selected_multipliers,
        )
        generated_json = json.dumps(generated, ensure_ascii=False, indent=2) + "\n"
        st.caption(
            "Lagre dette som config/saxo_instruments.json i repoet. Filen brukes automatisk av både web og worker."
        )
        st.code(generated_json, language="json")
        st.download_button(
            "Last ned saxo_instruments.json",
            data=generated_json,
            file_name="saxo_instruments.json",
            mime="application/json",
            use_container_width=True,
        )

st.subheader("Konfigurerte instrumenter")
st.caption(
    "Standardkilde: config/saxo_instruments.json. SAXO_INSTRUMENTS_JSON er kun en valgfri overstyring."
)
try:
    instruments = configured_instruments()
except ValueError as exc:
    st.error(f"Instrumentkonfigurasjonen er ugyldig: {exc}")
    instruments = {}
if not instruments:
    st.warning("Ingen instrumenter er konfigurert i config/saxo_instruments.json.")
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

st.subheader("Gull/sølv-ratio")
st.caption("Ratioen beregnes fra samtidige Saxo-priser; den er ikke et eget Saxo-instrument.")
if not connected:
    st.info("Koble til Saxo før ratioen beregnes.")
elif not {"Gold", "Silver"}.issubset(instruments):
    st.info("Konfigurer både Gold og Silver før ratioen beregnes.")
elif st.button("Beregn gull/sølv-ratio", use_container_width=True):
    try:
        ratio_client = configured_client()
        if ratio_client is None:
            raise RuntimeError("Saxo-klienten kunne ikke opprettes.")
        gold = ratio_client.chart(instruments["Gold"], horizon_minutes=5, count=12)
        silver = ratio_client.chart(instruments["Silver"], horizon_minutes=5, count=12)
        ratio = latest_gold_silver_ratio(gold, silver)
        r1, r2, r3 = st.columns(3)
        r1.metric("Gull", f"{ratio['gold']:,.3f}")
        r2.metric("Sølv", f"{ratio['silver']:,.3f}")
        r3.metric("Gull/sølv", f"{ratio['ratio']:,.2f}")
        st.caption(f"Siste synkroniserte observasjon: {ratio['timestamp']}")
    except Exception as exc:
        st.error(f"Ratioen kunne ikke beregnes: {exc}")
