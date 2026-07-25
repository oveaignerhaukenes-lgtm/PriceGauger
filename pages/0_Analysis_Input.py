from __future__ import annotations

from datetime import datetime, timezone
import uuid

import streamlit as st

from analysis_input import AnalysisInput, canonical_event_from_input, interpret_analysis_input
from build_info import render_build_badge
from event_dna import build_event_dna
from market_state_service import process_market_event
from telegram_query_builder import fetch_latest_search_plan
from worker import build_interpreter

st.set_page_config(page_title="Analysis Input", page_icon="🧠", layout="wide")
render_build_badge()


def _run(value: AnalysisInput, requested_type: str) -> dict:
    semantic = interpret_analysis_input(value, requested_type=requested_type)
    canonical = canonical_event_from_input(value, semantic)
    interpreter, interpreter_name = build_interpreter()

    # Only factual events enter the persistent live Market State. Searches and
    # scenarios are interpreted as previews and cannot contaminate event history.
    if semantic.input_type == "EVENT":
        result = process_market_event(canonical, interpreter=interpreter)
        market_interpretation = result.interpretation
        persisted = True
    else:
        market_interpretation = interpreter.interpret(canonical, update_type="CONTEXT")
        persisted = False

    dna = build_event_dna(canonical.to_market_event())
    record = {
        "input": value,
        "semantic": semantic,
        "canonical": canonical,
        "market_interpretation": market_interpretation,
        "event_dna": dna,
        "interpreter": interpreter_name,
        "persisted": persisted,
    }
    st.session_state.analysis_input_result = record
    st.session_state.canonical_telegram_event = canonical.to_record()
    st.session_state.canonical_market_event = canonical.to_market_event()
    st.session_state.gdelt_search = semantic.search
    st.session_state.gdelt_country = semantic.country
    st.session_state.gdelt_domain = semantic.domain
    st.session_state.analysis_input_assets = list(semantic.affected_assets)
    return record


def _render_result(record: dict) -> None:
    value = record["input"]
    semantic = record["semantic"]
    canonical = record["canonical"]
    market = record["market_interpretation"]
    dna = record["event_dna"]

    st.markdown("### 1 · Input")
    with st.container(border=True):
        i1, i2, i3 = st.columns(3)
        i1.metric("Kilde", value.source)
        i2.metric("Input-type", semantic.input_type)
        i3.metric("Lagret som faktisk hendelse", "Ja" if record["persisted"] else "Nei")
        st.write(value.raw_text)
        if value.source_url:
            st.link_button("Åpne kilde", value.source_url)

    st.markdown("### 2 · Fri AI-tolkning")
    with st.container(border=True):
        st.write(semantic.summary)
        a1, a2, a3, a4 = st.columns(4)
        a1.metric("Hendelsestype", semantic.event_type)
        a2.metric("Mål", semantic.target)
        a3.metric("Land", semantic.country or "Ukjent")
        a4.metric("Semantisk confidence", f"{semantic.confidence:.0%}")
        st.write(f"**Berørte instrumenter:** {', '.join(semantic.affected_assets) or 'Ikke bestemt'}")
        st.write(f"**Generert søk:** `{semantic.search}`")
        if semantic.uncertainties:
            st.write("**Usikkerhet:**")
            for item in semantic.uncertainties:
                st.write(f"• {item}")
        st.caption(f"Semantisk modell: {semantic.model_version}")

    st.markdown("### 3 · Market interpretation")
    with st.container(border=True):
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Novelty", f"{market.novelty:.0%}")
        m2.metric("Confidence", f"{market.confidence:.0%}")
        m3.metric("Source quality", f"{market.source_quality:.0%}")
        m4.metric("Update type", market.update_type)
        st.write(market.summary)
        for name, value_delta in market.state_deltas.items():
            st.write(f"**{name}:** {value_delta:+.2f}")
        if market.evidence:
            st.write("**Evidens:**")
            for item in market.evidence:
                st.write(f"• {item}")

    st.markdown("### 4 · EventDNA")
    with st.container(border=True):
        d1, d2, d3, d4 = st.columns(4)
        d1.metric("Type", dna.event_type)
        d2.metric("Mål", dna.target)
        d3.metric("Severity", f"{dna.severity:.0%}")
        d4.metric("Source quality", f"{dna.source_quality:.0%}")
        with st.expander("Komplett EventDNA"):
            st.json(dna.to_record())

    st.markdown("### 5 · Sendt videre i motoren")
    st.write(
        "CanonicalEvent → EventDNA → historisk søk → instrumentpåvirkning → "
        "World State / Technical → Combined."
    )
    st.page_link("pages/1_Historical_Event_Lab.py", label="Åpne Historical Event Lab", icon="🔎")
    st.page_link("pages/2_Direct_Technical.py", label="Åpne Direct Technical", icon="📈")
    st.page_link("pages/2_Signalaggregat.py", label="Åpne Signalaggregat / Combined", icon="∑")


st.title("Analysis Input")
st.caption(
    "Felles inngang til motoren. Automatiske Telegram-hendelser og manuelle hendelser, søk og "
    "scenarioer går gjennom samme semantiske AI-tolkning før EventDNA og markedsanalyse."
)

manual_tab, telegram_tab = st.tabs(["Manuell analyse / søk", "Siste Telegram-input"])

with manual_tab:
    requested_label = st.selectbox(
        "Hva slags input er dette?",
        ["Auto", "Faktisk hendelse", "Søk etter informasjon", "Hypotetisk scenario"],
    )
    requested_type = {
        "Auto": "AUTO",
        "Faktisk hendelse": "EVENT",
        "Søk etter informasjon": "SEARCH_REQUEST",
        "Hypotetisk scenario": "SCENARIO",
    }[requested_label]
    text = st.text_area(
        "Nyhet, spørsmål, scenario eller søkeønske",
        height=130,
        placeholder="Eksempel: Finn siste utvikling rundt Hormuz og analyser mulig effekt på Brent og gull.",
    )
    if st.button("Tolk og send gjennom motoren", type="primary", use_container_width=True):
        if not text.strip():
            st.warning("Skriv inn noe som skal analyseres.")
        else:
            value = AnalysisInput(
                input_id=str(uuid.uuid4()),
                input_type=requested_type,
                source="MANUAL",
                raw_text=text.strip(),
                published_at=datetime.now(timezone.utc).isoformat(),
            )
            try:
                with st.spinner("AI tolker input og bygger analyseobjekter …"):
                    _run(value, requested_type)
            except Exception as exc:
                st.error(f"Kunne ikke tolke input: {exc}")

with telegram_tab:
    if st.button("Hent og analyser siste relevante Telegram-melding", use_container_width=True):
        try:
            plan = fetch_latest_search_plan()
            if plan is None:
                st.info("Ingen relevant Telegram-melding ble funnet.")
            else:
                value = AnalysisInput(
                    input_id=plan.message_id,
                    input_type="EVENT",
                    source="TELEGRAM",
                    raw_text=plan.message_text,
                    source_url=plan.message_url,
                    published_at=plan.published_at,
                )
                with st.spinner("AI tolker Telegram-meldingen og sender den gjennom motoren …"):
                    _run(value, "EVENT")
        except Exception as exc:
            st.error(f"Kunne ikke analysere Telegram-input: {exc}")

result = st.session_state.get("analysis_input_result")
if result:
    st.divider()
    _render_result(result)
else:
    st.info("Velg en input-kilde og kjør analysen. Resultatet blir liggende mens du navigerer mellom sidene.")
