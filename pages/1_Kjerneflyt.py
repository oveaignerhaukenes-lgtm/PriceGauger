from __future__ import annotations

import pandas as pd
import streamlit as st

from config import gdelt_provider
from telegram_gdelt_presenter import (
    latest_result_candidate_rows,
    latest_result_summary,
)
from telegram_gdelt_service import process_latest_telegram_with_gdelt


st.set_page_config(page_title="PriceGauger kjerneflyt", page_icon="🔗", layout="wide")
st.title("🔗 Kjerneflyt: Telegram → historiske kandidater")
st.caption(
    "Behandler én relevant Telegram-post gjennom AI-tolkning, GDELT og SQLite. "
    "Denne siden rangerer ikke kandidatene og gir ingen markedsanbefaling."
)

active_provider = gdelt_provider()
provider_label = {
    "bigquery": "GDELT BigQuery",
    "direct": "GDELT DOC",
    "cloud": "GDELT Cloud",
    "auto": "Automatisk",
}.get(active_provider, active_provider)
st.caption(f"Aktiv datakilde: **{provider_label}**")

with st.sidebar:
    st.header("Innhenting")
    channel = st.text_input("Telegram-kanal", value="Middle_East_Spectator")
    lookback_days = st.number_input("Historisk vindu (dager)", min_value=1, max_value=365, value=30)
    limit = st.number_input("Maks kandidater", min_value=1, max_value=250, value=10)
    minimum_signal = st.number_input("Minste signalscore", min_value=1, max_value=3, value=2)

result_key = "latest_telegram_gdelt_result"
result_provider_key = "latest_telegram_gdelt_provider"

# Do not keep showing candidates from an older provider after configuration changes.
if st.session_state.get(result_provider_key) not in (None, active_provider):
    st.session_state.pop(result_key, None)
    st.session_state.pop(result_provider_key, None)

if st.button("Behandle nyeste relevante post", type="primary", use_container_width=True):
    try:
        with st.spinner("Tolker Telegram-post og henter historiske GDELT-kandidater …"):
            result = process_latest_telegram_with_gdelt(
                channel=channel,
                lookback_days=int(lookback_days),
                limit=int(limit),
                minimum_signal=int(minimum_signal),
                timeout=60,
            )
        st.session_state[result_key] = result
        st.session_state[result_provider_key] = active_provider
    except Exception as exc:
        st.error(f"Kjerneflyten kunne ikke fullføres: {exc}")

result = st.session_state.get(result_key)
if result is None:
    st.info("Ingen behandlet Telegram-post er lastet i denne økten.")
else:
    summary = latest_result_summary(result)
    st.subheader("Behandlet Telegram-post")
    st.write(summary["message_text"])
    if summary["message_url"]:
        st.link_button("Åpne posten i Telegram", summary["message_url"])

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Hendelsestype", summary["event_type"] or "ukjent")
    c2.metric("Mål", summary["target"] or "ukjent")
    c3.metric("Land", summary["country"] or "ikke angitt")
    c4.metric("Lagrede kandidater", summary["candidate_count"])

    source = summary["interpretation_source"] or "ukjent"
    model = summary["interpretation_model"] or "—"
    confidence = summary["interpretation_confidence"]
    confidence_text = f"{confidence * 100:.0f} %" if confidence is not None else "—"
    st.markdown("**AI-tolkning**")
    st.caption(f"Kilde: {source} · modell: {model} · confidence: {confidence_text}")

    details = []
    if summary["actor"]:
        details.append(f"Aktør: {summary['actor']}")
    if summary["market_channel"]:
        details.append(f"Markedskanal: {summary['market_channel']}")
    if summary["search_terms"]:
        details.append("Søkebegreper: " + " · ".join(summary["search_terms"]))
    if details:
        st.write("  \n".join(details))

    st.caption(
        f"BigQuery-søk: {summary['search']} · search_id: {summary['search_id']} · "
        f"lagrede søk for meldingen: {summary['search_count']}"
    )
    if summary["warning"]:
        st.warning(summary["warning"])

    rows = latest_result_candidate_rows(result)
    st.subheader("Historiske nyhetskandidater")
    if not rows:
        st.info("Ingen historiske kandidater ble lagret for dette søket.")
    else:
        frame = pd.DataFrame(rows)
        st.dataframe(
            frame,
            hide_index=True,
            use_container_width=True,
            column_config={
                "published_at": "Publisert",
                "title": "Tittel",
                "domain": "Domene",
                "source_country": "Kildeland",
                "provider": "Leverandør",
                "url": st.column_config.LinkColumn("Artikkel"),
            },
        )
