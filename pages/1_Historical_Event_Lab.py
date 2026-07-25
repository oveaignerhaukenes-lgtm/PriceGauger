from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from analysis_event_store import list_analysis_events
from event_lab_ui import REACTION_ASSETS, _run_pipeline
from telegram_query_builder import TelegramSearchPlan
from ui_components import render_pipeline_breadcrumb

st.set_page_config(page_title="Historical Event Lab", page_icon="🧭", layout="wide")
render_pipeline_breadcrumb()

analysis_events = list_analysis_events(limit=100)
if not analysis_events:
    st.title("Historical Event Lab")
    st.info("Ingen Canonical Events finnes ennå. Åpne Analysis Input først; siste Telegram-input blir analysert og lagret automatisk.")
    st.page_link("pages/0_Analysis_Input.py", label="Åpne Analysis Input", icon="🧠")
    st.stop()


def _event_label(event: dict) -> str:
    timestamp = (event.get("published_at") or event.get("created_at") or "")[:16].replace("T", " ")
    summary = event.get("summary") or event.get("raw_text") or event.get("event_id")
    channel = event.get("source_channel") or event.get("source") or ""
    return f"{timestamp} · {channel} · {summary[:90]}"


def _selected_plan(event: dict) -> TelegramSearchPlan:
    return TelegramSearchPlan(
        message_id=str(event.get("event_id") or "historical-selection"),
        message_url=str(event.get("source_url") or ""),
        message_text=str(event.get("raw_text") or event.get("summary") or ""),
        event_type=str(event.get("event_type") or "event"),
        target=str(event.get("target") or "unspecified"),
        country=str(event.get("country") or ""),
        domain=str(event.get("domain") or ""),
        search=str(event.get("search_query") or event.get("summary") or event.get("raw_text") or ""),
        signal_score=3,
        published_at=str(event.get("published_at") or event.get("created_at") or ""),
    )


with st.sidebar:
    st.header("Analyseobjekt")
    selected_index = st.selectbox(
        "Canonical Event",
        options=range(len(analysis_events)),
        index=0,
        format_func=lambda index: _event_label(analysis_events[index]),
    )
    days = st.selectbox("Historisk søkevindu", [14, 30, 90, 180, 365], index=1, format_func=lambda value: f"{value} dager")
    limit = st.slider("Maks GDELT-kandidater", 5, 100, 50, 5)
    selected_assets = st.multiselect("Markeder", list(REACTION_ASSETS), default=list(REACTION_ASSETS))
    refresh = st.button("Oppdater historisk analyse", type="primary", use_container_width=True)

selected = analysis_events[selected_index]
plan = _selected_plan(selected)
st.markdown(
    "<div style='font-size:.68rem;letter-spacing:.09em;text-transform:uppercase;color:rgba(128,128,128,.88);'>GDELT / HISTORICAL EVENT LAB</div>",
    unsafe_allow_html=True,
)
st.title(selected.get("summary") or selected.get("raw_text", "Canonical Event"))
st.caption(
    f"{selected.get('source_channel') or selected.get('source')} · "
    f"{selected.get('published_at') or 'ukjent tidspunkt'} · "
    f"BigQuery-first søk: {plan.search or 'ikke generert'}"
)

if not selected_assets:
    st.info("Velg minst ett marked.")
    st.stop()

end_date = date.today()
start_date = end_date - timedelta(days=days)
signature = (
    selected.get("event_id"),
    start_date.isoformat(),
    end_date.isoformat(),
    limit,
    tuple(sorted(selected_assets)),
    "bigquery-first-v1",
)
if refresh or st.session_state.get("historical_page_signature") != signature:
    st.session_state.historical_page_signature = signature
    _run_pipeline(
        plan=plan,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        selected_assets=selected_assets,
    )

status = st.session_state.get("gdelt_historical_status", "NOT_ANALYSED")
summary = st.session_state.get("gdelt_pipeline_summary") or {}
warning = st.session_state.get("gdelt_pipeline_error")
if warning:
    st.warning(warning)

provider = summary.get("provider", "IKKE KJØRT")
st.caption(f"Status: {status} · Kilde: {provider} · EventSignal sendes automatisk til Signalaggregat.")

m1, m2, m3, m4, m5, m6 = st.columns(6)
m1.metric("Kilde", provider)
m2.metric("Analoger", summary.get("analogues", 0))
m3.metric("Med klokkeslett", summary.get("precise", 0))
m4.metric("Intradag", summary.get("intraday", 0))
m5.metric("Daglig", summary.get("daily", 0))
m6.metric("EventSignal", summary.get("signals", 0))

matches = st.session_state.get("gdelt_analogue_matches", [])
st.subheader("Rangerte GDELT-analoger")
if matches:
    frame = pd.DataFrame([
        {
            "likhet": item.get("score"),
            "dato": (item.get("event") or {}).get("event_date"),
            "hendelse": (item.get("event") or {}).get("title"),
            "land": (item.get("event") or {}).get("country"),
            "type": (item.get("dna") or {}).get("event_type"),
            "mål": (item.get("dna") or {}).get("target"),
        }
        for item in matches
    ])
    st.dataframe(
        frame,
        use_container_width=True,
        hide_index=True,
        column_config={"likhet": st.column_config.NumberColumn("Likhet", format="%.1%%")},
    )
else:
    st.info("Ingen historiske analoger er tilgjengelige for dette analyseobjektet.")

intraday = st.session_state.get("gdelt_intraday_reactions", [])
st.subheader("Analog → markedsreaksjon")
if intraday:
    reaction_frame = pd.DataFrame([item.to_record() for item in intraday])
    st.dataframe(
        reaction_frame.reindex(columns=[
            "event_title", "asset", "published_at", "quality_score",
            "return_1h_pct", "return_4h_pct", "return_24h_pct",
        ]),
        use_container_width=True,
        hide_index=True,
    )
else:
    st.info("Ingen intradagreaksjoner tilgjengelig for analogutvalget.")

st.page_link("pages/2_Signalaggregat.py", label="Åpne Signalaggregat / Combined", icon="📊")
