from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from config import gdelt_provider
from engine_sidebar import render_engine_sidebar
from historical_engine import build_historical_assessment
from saxo_analogue_reactions import measure_brent_reactions
from saxo_provider import configured_client
from telegram_gdelt_presenter import (
    latest_result_candidate_rows,
    latest_result_summary,
)
from telegram_gdelt_service import process_latest_telegram_with_gdelt


st.set_page_config(page_title="PriceGauger historisk motor", page_icon="🔗", layout="wide")
st.title("🔗 Historisk motor")
st.caption(
    "Tolker en ny Telegram-hendelse, finner historiske GDELT-kandidater og måler observerte "
    "Brent-reaksjoner. Prisvurderingen er foreløpig urankert og skal ikke brukes som en "
    "selvstendig handelsanbefaling."
)

active_provider = gdelt_provider()
provider_label = {
    "bigquery": "GDELT BigQuery",
    "direct": "GDELT DOC",
    "cloud": "GDELT Cloud",
    "auto": "Automatisk",
}.get(active_provider, active_provider)
st.caption(f"Aktiv datakilde: **{provider_label}**")

render_engine_sidebar(active="historical")
with st.sidebar:
    st.header("Innhenting")
    channel = st.text_input("Telegram-kanal", value="Middle_East_Spectator")
    lookback_days = st.number_input("Historisk vindu (dager)", min_value=1, max_value=365, value=30)
    limit = st.number_input("Maks kandidater", min_value=1, max_value=250, value=10)
    minimum_signal = st.number_input("Minste signalscore", min_value=1, max_value=3, value=2)

result_key = "latest_telegram_gdelt_result"
result_provider_key = "latest_telegram_gdelt_provider"
reaction_key = "latest_saxo_brent_reactions"
reaction_search_key = "latest_saxo_brent_search_id"

# Do not keep showing candidates or reactions from an older provider/search.
if st.session_state.get(result_provider_key) not in (None, active_provider):
    st.session_state.pop(result_key, None)
    st.session_state.pop(result_provider_key, None)
    st.session_state.pop(reaction_key, None)
    st.session_state.pop(reaction_search_key, None)

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
        st.session_state.pop(reaction_key, None)
        st.session_state.pop(reaction_search_key, None)
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

        st.subheader("Observerte Brent-reaksjoner · Saxo")
        st.caption(
            "Måler foreløpig alle returnerte kandidater. Semantisk rangering kobles på i neste lag. "
            "Kun kandidater med eksakt publiseringstid kan måles."
        )
        if st.button("Hent Brent-reaksjoner fra Saxo", use_container_width=True):
            client = configured_client()
            if client is None:
                st.error("Saxo OAuth er ikke konfigurert eller tilkoblet.")
            else:
                try:
                    with st.spinner("Velger historiske Brent-kontrakter og henter prisvinduer …"):
                        reactions = measure_brent_reactions(result.ingestion.candidates, client=client)
                    st.session_state[reaction_key] = [item.to_record() for item in reactions]
                    st.session_state[reaction_search_key] = summary["search_id"]
                except Exception as exc:
                    st.error(f"Saxo-reaksjonene kunne ikke hentes: {exc}")

        if st.session_state.get(reaction_search_key) == summary["search_id"]:
            reaction_rows = st.session_state.get(reaction_key, [])
            if reaction_rows:
                reaction_frame = pd.DataFrame(reaction_rows)
                st.dataframe(
                    reaction_frame,
                    hide_index=True,
                    use_container_width=True,
                    column_config={
                        "candidate_event_id": "Hendelse",
                        "published_at": "Tidspunkt",
                        "contract_symbol": "Kontrakt",
                        "contract_uic": "UIC",
                        "price_at_event": st.column_config.NumberColumn("Startpris", format="%.3f"),
                        "return_15m_pct": st.column_config.NumberColumn("+15m %", format="%.3f"),
                        "return_1h_pct": st.column_config.NumberColumn("+1t %", format="%.3f"),
                        "return_4h_pct": st.column_config.NumberColumn("+4t %", format="%.3f"),
                        "return_24h_pct": st.column_config.NumberColumn("+24t %", format="%.3f"),
                        "mfe_4h_pct": st.column_config.NumberColumn("MFE 4t %", format="%.3f"),
                        "mae_4h_pct": st.column_config.NumberColumn("MAE 4t %", format="%.3f"),
                        "status": "Status",
                        "error": "Feil",
                    },
                )

                assessment = build_historical_assessment(
                    reaction_rows,
                    source_search_id=summary["search_id"],
                    asset="Brent",
                )
                assessment_record = assessment.to_record()
                st.subheader("Historisk motor · prisvurdering")
                st.caption(
                    "Primærhorisont: 4 timer. Duplikate publiseringstidspunkter teller bare én gang. "
                    "Statusen er foreløpig urankert til semantisk analograngering er koblet på."
                )

                probability_up = assessment.probability_up
                probability_text = f"{probability_up * 100:.0f} % opp" if probability_up is not None else "—"
                expected_text = (
                    f"{assessment.expected_return_pct:+.2f} %"
                    if assessment.expected_return_pct is not None
                    else "—"
                )
                interval_text = (
                    f"{assessment.likely_interval_low_pct:+.2f} til {assessment.likely_interval_high_pct:+.2f} %"
                    if assessment.likely_interval_low_pct is not None
                    and assessment.likely_interval_high_pct is not None
                    else "—"
                )

                p1, p2, p3, p4, p5 = st.columns(5)
                p1.metric("Retning · 4t", assessment.forecast_direction)
                p2.metric("Sannsynlighet", probability_text)
                p3.metric("Median · 4t", expected_text)
                p4.metric("Sannsynlig intervall", interval_text)
                p5.metric("Confidence", f"{assessment.confidence * 100:.0f} %")

                st.write(
                    f"Uavhengige analogtidspunkter: **{assessment.independent_analogues}** · "
                    f"duplikater fjernet: **{assessment.duplicate_reactions_removed}** · "
                    f"status: **{assessment.status}**"
                )

                with st.expander("Hva ugyldiggjør eller begrenser vurderingen?"):
                    st.markdown("**Ugyldiggjøringskriterier**")
                    for item in assessment.invalidation_conditions:
                        st.write(f"- {item}")
                    st.markdown("**Begrensninger**")
                    for item in assessment.limitations:
                        st.write(f"- {item}")

                with st.expander("Strukturert motor-output"):
                    st.json(assessment_record)
                    st.download_button(
                        "Last ned vurdering som JSON",
                        data=json.dumps(assessment_record, ensure_ascii=False, indent=2),
                        file_name=f"{assessment.assessment_id.replace(':', '_')}.json",
                        mime="application/json",
                        use_container_width=True,
                    )
