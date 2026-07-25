from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from analysis_event_store import list_analysis_events
from config import gdelt_api_key
from gdelt_client import GdeltClient, GdeltError
from storage import save_events
from ui_components import render_pipeline_breadcrumb

st.set_page_config(page_title="Historical Event Lab", page_icon="🧭", layout="wide")
render_pipeline_breadcrumb()

api_key = gdelt_api_key()
if not api_key:
    st.error("GDELT_CLOUD_API_KEY mangler i Streamlit Secrets.")
    st.stop()

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


def _fetch_for_event(event: dict, *, days: int, limit: int, profile: str):
    end_date = date.today()
    start_date = end_date - timedelta(days=days)
    client = GdeltClient(api_key)
    return client.list_events(
        date_start=start_date.isoformat(),
        date_end=end_date.isoformat(),
        search=(event.get("search_query") or event.get("summary") or event.get("raw_text") or "")[:300],
        country=event.get("country") or "",
        category="",
        domain=event.get("domain") or "",
        event_family="",
        confidence_profile=profile,
        sort="significance",
        limit=limit,
    )


with st.sidebar:
    st.header("Analyseobjekt")
    selected_index = st.selectbox(
        "Canonical Event",
        options=range(len(analysis_events)),
        index=0,
        format_func=lambda index: _event_label(analysis_events[index]),
    )
    days = st.selectbox("Historisk søkevindu", [14, 30, 90, 180, 365], index=2, format_func=lambda value: f"{value} dager")
    limit = st.slider("Maks GDELT-resultater", 10, 100, 50, 10)
    confidence_profile = st.selectbox("Kvalitetsprofil", ["strictest", "precise", "balanced", "loose"], index=1)
    refresh = st.button("Oppdater historisk kontekst", type="primary", use_container_width=True)

selected = analysis_events[selected_index]
st.markdown(f"<div style='font-size:.72rem;letter-spacing:.08em;text-transform:uppercase;color:rgba(128,128,128,.9);'>GDELT / HISTORICAL EVENT LAB</div>", unsafe_allow_html=True)
st.title(selected.get("summary") or selected.get("raw_text", "Canonical Event"))
st.caption(
    f"{selected.get('source_channel') or selected.get('source')} · "
    f"{selected.get('published_at') or 'ukjent tidspunkt'} · "
    f"søk: {selected.get('search_query') or 'ikke generert'}"
)

cache_key = f"gdelt_for_{selected['event_id']}_{days}_{limit}_{confidence_profile}"
should_fetch = refresh or cache_key not in st.session_state
if should_fetch:
    try:
        with st.spinner("Henter automatisk relevante GDELT-hendelser til valgt Canonical Event …"):
            page = _fetch_for_event(selected, days=days, limit=limit, profile=confidence_profile)
            st.session_state[cache_key] = {
                "events": page.events,
                "next_cursor": page.next_cursor,
            }
            save_events(page.events)
    except (GdeltError, ValueError) as exc:
        st.error(f"GDELT-kallet mislyktes: {exc}")
    except Exception as exc:
        st.error(f"Uventet feil under GDELT-kallet: {exc}")

result = st.session_state.get(cache_key)
if not result:
    st.info("Ingen historisk kontekst er tilgjengelig for denne hendelsen ennå.")
    st.stop()

records = [event.to_record() for event in result["events"]]
if not records:
    st.warning("GDELT fant ingen relevante hendelser med de valgte kvalitetskravene. Utvid søkevinduet eller velg en løsere kvalitetsprofil.")
    st.stop()

frame = pd.DataFrame(records)
if "actors" in frame:
    frame["actors"] = frame["actors"].apply(lambda values: ", ".join(values) if isinstance(values, list) else str(values or ""))

confidence = pd.to_numeric(frame.get("confidence"), errors="coerce").fillna(0.0)
sensitivity = pd.to_numeric(frame.get("market_sensitivity"), errors="coerce").fillna(0.0)
significance = pd.to_numeric(frame.get("significance"), errors="coerce").fillna(0.0)
frame["historical_relevance_score"] = (confidence * 0.30 + sensitivity * 0.35 + significance * 0.35).round(3)
frame = frame.sort_values("historical_relevance_score", ascending=False)

m1, m2, m3, m4 = st.columns(4)
m1.metric("Historiske kandidater", len(frame))
m2.metric("Gjennomsnittlig relevans", f"{frame['historical_relevance_score'].mean():.3f}")
m3.metric("Sterkeste analog", f"{frame['historical_relevance_score'].max():.3f}")
m4.metric("Neste resultatside", "Ja" if result.get("next_cursor") else "Nei")

st.subheader("Rangerte historiske kandidater")
visible_columns = [
    column for column in [
        "event_date", "title", "country", "category", "domain", "confidence",
        "market_sensitivity", "significance", "historical_relevance_score", "url"
    ] if column in frame.columns
]
st.dataframe(
    frame[visible_columns],
    use_container_width=True,
    hide_index=True,
    column_config={
        "url": st.column_config.LinkColumn("Kilde"),
        "historical_relevance_score": st.column_config.NumberColumn("Relevans", format="%.3f"),
    },
)

st.subheader("Historisk evidens til Signalaggregat")
st.write(
    "GDELT-resultatet er nå automatisk bundet til valgt Canonical Event og lagret i den felles databasen. "
    "Retningsscore skal ikke utledes av nyhetslikhet alene; den produseres først når de rangerte analogene "
    "er koblet til observerte markedsreaksjoner. Ferdige EventSignal-objekter blir deretter summert i Signalaggregat."
)

st.download_button(
    "Last ned rangerte analoger som CSV",
    frame.drop(columns=["raw"], errors="ignore").to_csv(index=False).encode("utf-8"),
    f"historical_analogues_{selected['event_id'].replace(':', '_')}.csv",
    "text/csv",
    use_container_width=True,
)
