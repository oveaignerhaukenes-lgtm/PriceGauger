from __future__ import annotations

from datetime import datetime, timezone
import uuid

import streamlit as st

from analysis_event_store import save_analysis_event
from analysis_input import AnalysisInput, canonical_event_from_input, interpret_analysis_input
from build_info import render_build_badge
from event_dna import build_event_dna
from market_state_service import process_market_event
from telegram_query_builder import fetch_latest_search_plan
from ui_components import render_pipeline_breadcrumb
from worker import build_interpreter

st.set_page_config(page_title="Analysis Input", page_icon="🧠", layout="wide")
render_build_badge()
render_pipeline_breadcrumb()

DEFAULT_CHANNELS = ["Middle_East_Spectator", "Intel_Slava_Z", "warfareanalysis"]


def _configured_channels() -> list[str]:
    configured = st.secrets.get("telegram_channels", DEFAULT_CHANNELS)
    if isinstance(configured, str):
        configured = [item.strip() for item in configured.split(",")]
    channels = [str(item).strip().lstrip("@") for item in configured if str(item).strip()]
    return channels or DEFAULT_CHANNELS


def _source_channel(source_url: str | None) -> str:
    if not source_url:
        return ""
    parts = source_url.rstrip("/").split("/")
    return parts[-2] if len(parts) >= 2 else ""


def _run(value: AnalysisInput, requested_type: str) -> dict:
    semantic = interpret_analysis_input(value, requested_type=requested_type)
    canonical = canonical_event_from_input(value, semantic)
    interpreter, interpreter_name = build_interpreter()

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

    if semantic.input_type == "EVENT":
        save_analysis_event(
            event_id=value.input_id,
            published_at=value.published_at,
            source=value.source,
            source_channel=_source_channel(value.source_url),
            raw_text=value.raw_text,
            source_url=value.source_url or "",
            summary=semantic.summary,
            event_type=semantic.event_type,
            target=semantic.target,
            country=semantic.country,
            domain=semantic.domain,
            search_query=semantic.search,
            affected_assets=list(semantic.affected_assets),
            semantic_confidence=semantic.confidence,
            canonical=canonical.to_record(),
        )
    return record


def _latest_from_channels(channels: list[str]):
    candidates = []
    errors = []
    for channel in channels:
        try:
            plan = fetch_latest_search_plan(channel=channel)
            if plan is not None:
                candidates.append((channel, plan))
        except Exception as exc:
            errors.append(f"{channel}: {exc}")
    candidates.sort(key=lambda item: item[1].published_at or "", reverse=True)
    return (candidates[0] if candidates else None), errors


def _analyse_latest(channels: list[str]) -> None:
    latest, errors = _latest_from_channels(channels)
    st.session_state.telegram_channel_errors = errors
    if latest is None:
        st.session_state.telegram_empty = True
        return
    channel, plan = latest
    value = AnalysisInput(
        input_id=f"telegram:{channel}:{plan.message_id}",
        input_type="EVENT",
        source="TELEGRAM",
        raw_text=plan.message_text,
        source_url=plan.message_url,
        published_at=plan.published_at,
    )
    _run(value, "EVENT")
    st.session_state.telegram_empty = False
    st.session_state.telegram_selected_channel = channel


def _render_result(record: dict) -> None:
    value = record["input"]
    semantic = record["semantic"]
    canonical = record["canonical"]
    market = record["market_interpretation"]
    dna = record["event_dna"]

    st.markdown(f"## {semantic.summary or value.raw_text[:100]}")
    st.caption(f"{value.source} · {_source_channel(value.source_url) or 'manuell'} · {value.published_at or 'ukjent tidspunkt'}")

    st.markdown("### AI interpretation")
    with st.container(border=True):
        st.write(semantic.summary)
        a1, a2, a3, a4 = st.columns(4)
        a1.metric("Type", semantic.event_type)
        a2.metric("Mål", semantic.target)
        a3.metric("Land", semantic.country or "Ukjent")
        a4.metric("Confidence", f"{semantic.confidence:.0%}")
        st.write(f"**Instrumenter:** {', '.join(semantic.affected_assets) or 'Ikke bestemt'}")
        st.write(f"**GDELT-søk:** `{semantic.search}`")

    st.markdown("### Market interpretation")
    with st.container(border=True):
        m1, m2, m3 = st.columns(3)
        m1.metric("Novelty", f"{market.novelty:.0%}")
        m2.metric("Confidence", f"{market.confidence:.0%}")
        m3.metric("Source quality", f"{market.source_quality:.0%}")
        st.write(market.summary)

    with st.expander("Canonical Event og EventDNA"):
        st.json({"canonical_event": canonical.to_record(), "event_dna": dna.to_record()})

    st.page_link("pages/1_Historical_Event_Lab.py", label="Åpne automatisk GDELT / Historical Event Lab", icon="🔎")
    st.page_link("pages/2_Signalaggregat.py", label="Åpne Signalaggregat / Combined", icon="📊")


st.title("Analysis Input")
st.caption("Siste relevante Telegram-hendelse er standard analyseobjekt. Alle faktiske hendelser lagres som Canonical Events og følger samme analyseflyt.")

channels = _configured_channels()
with st.sidebar:
    st.header("Input streams")
    selected_channels = st.multiselect(
        "Aktive Telegram-kanaler",
        options=channels,
        default=channels,
        help="Legg flere kanaler i Streamlit Secrets som telegram_channels.",
    )
    st.caption(f"{len(selected_channels)} aktive strømmer")
    refresh = st.button("Hent siste nå", type="primary", use_container_width=True)

telegram_tab, manual_tab = st.tabs(["Siste Telegram-input", "Manuell analyse / søk"])

with telegram_tab:
    should_auto_load = "analysis_input_result" not in st.session_state and not st.session_state.get("telegram_autoload_attempted")
    if should_auto_load or refresh:
        st.session_state.telegram_autoload_attempted = True
        if not selected_channels:
            st.warning("Velg minst én Telegram-kanal.")
        else:
            with st.spinner("Henter siste relevante melding fra aktive Telegram-strømmer …"):
                try:
                    _analyse_latest(selected_channels)
                except Exception as exc:
                    st.error(f"Kunne ikke analysere Telegram-input: {exc}")

    errors = st.session_state.get("telegram_channel_errors", [])
    if errors:
        with st.expander(f"{len(errors)} kanalfeil"):
            for error in errors:
                st.write(error)
    if st.session_state.get("telegram_empty"):
        st.info("Ingen relevant Telegram-melding ble funnet i de aktive kanalene.")

    result = st.session_state.get("analysis_input_result")
    if result:
        _render_result(result)

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
    text = st.text_area("Nyhet, spørsmål, scenario eller søkeønske", height=130)
    if st.button("Tolk og send gjennom motoren", use_container_width=True):
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
                    _render_result(_run(value, requested_type))
            except Exception as exc:
                st.error(f"Kunne ikke tolke input: {exc}")
