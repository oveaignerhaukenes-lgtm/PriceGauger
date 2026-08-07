from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from engine_sidebar import render_engine_sidebar
from news_context_engine import OpenAINewsContextEngine
from news_context_store import NewsContextStore
from telegram_query_builder import fetch_search_plans


st.set_page_config(page_title="PriceGauger nyhetsmotor", page_icon="📰", layout="wide")
st.title("📰 Nyhetsmotor")
st.caption(
    "Bygger en gjenbrukbar nyhets- og konfliktkontekst for ett valgt tidspunkt. "
    "Samme motor kan senere kjøres både for nåtid og før historiske analoghendelser."
)

render_engine_sidebar(active="news")
with st.sidebar:
    st.header("Nyhetskontekst")
    channel = st.text_input("Telegram-kanal", value="Middle_East_Spectator", key="news_channel")
    minimum_signal = st.number_input("Minste signalscore", min_value=1, max_value=3, value=1, key="news_signal")
    use_now = st.checkbox("Analyser nå", value=True)
    historical_as_of = st.text_input(
        "Historisk as_of (ISO-8601)",
        value="",
        disabled=use_now,
        help="Eksempel: 2026-07-24T12:00:00Z",
    )

result_key = "latest_news_context_assessment"

if st.button("Analyser nyhetskontekst", type="primary", use_container_width=True):
    try:
        with st.spinner("Henter Telegram-strøm og vurderer 1t / 4t / 12t / 24t / 7d …"):
            plans = fetch_search_plans(
                channel,
                minimum_signal=int(minimum_signal),
                timeout=45,
            )
            if not plans:
                raise RuntimeError("Ingen relevante Telegram-poster ble hentet.")
            as_of = None if use_now else historical_as_of.strip()
            if not use_now and not as_of:
                raise ValueError("Historisk as_of må angis når 'Analyser nå' er slått av.")
            assessment = OpenAINewsContextEngine().assess(
                plans,
                channel=channel,
                as_of=as_of,
            )
            NewsContextStore().save(assessment)
        st.session_state[result_key] = assessment.to_record()
    except Exception as exc:
        st.error(f"Nyhetsmotoren kunne ikke fullføres: {exc}")

persisted = NewsContextStore().load_latest()
record = st.session_state.get(result_key) or (persisted.to_record() if persisted is not None else None)
if record is None:
    st.info("Ingen nyhetskontekst er lagret ennå.")
else:
    if result_key not in st.session_state:
        st.success("Viser siste nyhetskontekst lagret av produksjonsworkeren.")
    if record.get("coverage_warning"):
        st.warning(record["coverage_warning"])

    st.subheader("Regimetilstand")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Konfliktnivå", f"{record['conflict_level'] * 100:.0f} %")
    c2.metric("Fryktnivå", f"{record['fear_level'] * 100:.0f} %")
    c3.metric("Forsyningsrisiko", f"{record['physical_supply_risk'] * 100:.0f} %")
    c4.metric("Narrativ metning", f"{record['narrative_saturation'] * 100:.0f} %")
    c5.metric("Bekreftelseskvalitet", f"{record['confirmation_quality'] * 100:.0f} %")

    st.markdown(f"### {record['regime_label']}")
    st.write(record["summary"])
    st.caption(
        f"as_of: {record['as_of']} · retning: {record['escalation_direction']} · "
        f"confidence: {record['confidence'] * 100:.0f} % · modell: {record['model']}"
    )

    left, middle, right = st.columns(3)
    with left:
        st.markdown("**Aktive drivere**")
        for item in record.get("active_drivers", []):
            st.write(f"- {item}")
    with middle:
        st.markdown("**Motsignaler**")
        for item in record.get("counter_signals", []):
            st.write(f"- {item}")
    with right:
        st.markdown("**Åpne spørsmål**")
        for item in record.get("unresolved_questions", []):
            st.write(f"- {item}")

    st.subheader("Tidsvinduer")
    window_rows = [
        {
            "window": "7d" if item["hours"] == 168 else f"{item['hours']}t",
            "posts": item["post_count"],
            "first_post": item["first_post_at"],
            "last_post": item["last_post_at"],
        }
        for item in record.get("windows", [])
    ]
    st.dataframe(pd.DataFrame(window_rows), hide_index=True, use_container_width=True)
    st.caption(
        f"Kildedekning: {record.get('coverage_start') or 'ukjent'} → "
        f"{record.get('coverage_end') or 'ukjent'} · hentede poster: {record['source_post_count']}"
    )

    with st.expander("Strukturert motor-output"):
        st.json(record)
        st.download_button(
            "Last ned nyhetskontekst som JSON",
            data=json.dumps(record, ensure_ascii=False, indent=2),
            file_name="news_context_assessment.json",
            mime="application/json",
            use_container_width=True,
        )
