from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from config import gdelt_provider
from engine_sidebar import render_engine_sidebar
from historical_engine import build_historical_assessment
from historical_engine_ui import (
    compact_timestamp,
    render_event_summary,
    render_historical_assessment,
    render_semantic_ranking_table,
)
from saxo_analogue_reactions import measure_brent_reactions
from saxo_provider import configured_client
from semantic_analogue_ranking import rank_analogues, select_reactions_for_ranked_analogues
from telegram_gdelt_presenter import latest_result_candidate_rows, latest_result_summary
from telegram_gdelt_service import process_latest_telegram_with_gdelt


st.set_page_config(page_title="PriceGauger historisk motor", page_icon="🔗", layout="wide")
st.title("🔗 Historisk motor")
st.caption(
    "Tolker en ny Telegram-hendelse, finner historiske GDELT-kandidater og måler observerte "
    "Brent-reaksjoner. Prisvurderingen bruker bare kandidater som passerer den semantiske filtreringen."
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
semantic_key = "latest_semantic_analogue_ranking"
semantic_search_key = "latest_semantic_analogue_search_id"


def _clear_derived_results() -> None:
    st.session_state.pop(reaction_key, None)
    st.session_state.pop(reaction_search_key, None)
    st.session_state.pop(semantic_key, None)
    st.session_state.pop(semantic_search_key, None)


if st.session_state.get(result_provider_key) not in (None, active_provider):
    st.session_state.pop(result_key, None)
    st.session_state.pop(result_provider_key, None)
    _clear_derived_results()

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
        _clear_derived_results()
    except Exception as exc:
        st.error(f"Kjerneflyten kunne ikke fullføres: {exc}")

result = st.session_state.get(result_key)
if result is None:
    st.info("Ingen behandlet Telegram-post er lastet i denne økten.")
else:
    summary = latest_result_summary(result)
    st.subheader("Behandlet Telegram-post")
    st.write(summary["message_text"])
    st.caption(f"Publisert {compact_timestamp(result.plan.published_at)}")
    if summary["message_url"]:
        st.link_button("Åpne posten i Telegram", summary["message_url"])

    render_event_summary(summary)

    source = summary["interpretation_source"] or "ukjent"
    model = summary["interpretation_model"] or "—"
    confidence = summary["interpretation_confidence"]
    confidence_text = f"{confidence * 100:.0f} %" if confidence is not None else "—"
    st.markdown("**AI-tolkning**")
    st.caption(f"Kilde: {source} · modell: {model} · confidence: {confidence_text}")

    if summary["actor"]:
        st.write(f"**Aktør:** {summary['actor']}")
    if summary["market_channel"]:
        st.write(f"**Markedskanal:** {summary['market_channel']}")
    if summary["search_terms"]:
        st.write("**Søkebegreper:** " + " · ".join(summary["search_terms"]))

    with st.expander("Tekniske søkedetaljer"):
        st.write(f"**BigQuery-søk:** {summary['search']}")
        st.write(f"**search_id:** {summary['search_id']}")
        st.write(f"**Lagrede søk for meldingen:** {summary['search_count']}")
    if summary["warning"]:
        st.warning(summary["warning"])

    rows = latest_result_candidate_rows(result)
    st.subheader("Historiske nyhetskandidater")
    if not rows:
        st.info("Ingen historiske kandidater ble lagret for dette søket.")
    else:
        candidate_records = []
        for row in rows:
            item = dict(row)
            item["published_at"] = compact_timestamp(item.get("published_at"))
            candidate_records.append(item)
        frame = pd.DataFrame(candidate_records)
        preferred = ["published_at", "title", "domain", "source_country", "provider", "url"]
        technical = [column for column in frame.columns if column not in preferred]
        st.dataframe(
            frame,
            hide_index=True,
            use_container_width=True,
            column_order=tuple(column for column in preferred + technical if column in frame.columns),
            column_config={
                "published_at": st.column_config.TextColumn("Publisert", width="small"),
                "title": st.column_config.TextColumn("Tittel", width="large"),
                "domain": "Domene",
                "source_country": "Kildeland",
                "provider": "Leverandør",
                "url": st.column_config.LinkColumn("Artikkel"),
                "event_id": st.column_config.TextColumn("Teknisk hendelses-ID", width="medium"),
            },
        )

        st.subheader("Semantisk analoglikhet")
        st.caption(
            "AI vurderer både likhet mellom hendelsene og likhet som mulig årsak til markedsreaksjon. "
            "Prisvurderingen bruker bare kandidater som består alle tersklene."
        )
        if st.button("Vurder semantisk likhet", use_container_width=True):
            try:
                with st.spinner("Sammenligner kandidatene parallelt …"):
                    ranked = rank_analogues(result.plan, result.ingestion.candidates, limit=int(limit))
                st.session_state[semantic_key] = [item.to_record() for item in ranked]
                st.session_state[semantic_search_key] = summary["search_id"]
            except Exception as exc:
                st.error(f"Semantisk rangering kunne ikke fullføres: {exc}")

        semantic_ready = st.session_state.get(semantic_search_key) == summary["search_id"]
        semantic_rows = st.session_state.get(semantic_key, []) if semantic_ready else []
        if semantic_ready:
            render_semantic_ranking_table(semantic_rows)
            st.caption("Filter: hendelseslikhet ≥ 60 % · markedslikhet ≥ 50 % · samlet likhet ≥ 60 %.")

        st.subheader("Observerte Brent-reaksjoner · Saxo")
        st.caption("Saxo access-token fornyes automatisk så lenge det lagrede refresh-tokenet fortsatt er gyldig.")
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
                    message = str(exc)
                    st.error(f"Saxo-reaksjonene kunne ikke hentes: {message}")
                    if "REAUTH_REQUIRED" in message or "AUTH_FAILED" in message:
                        st.info(
                            "Access-token fornyes automatisk. Denne feilen betyr vanligvis at også "
                            "refresh-tokenet er utløpt eller avvist, og Saxo må kobles til på nytt."
                        )

        if st.session_state.get(reaction_search_key) == summary["search_id"]:
            reaction_rows = st.session_state.get(reaction_key, [])
            if reaction_rows:
                display_rows = []
                for row in reaction_rows:
                    item = dict(row)
                    item["published_at"] = compact_timestamp(item.get("published_at"))
                    display_rows.append(item)
                reaction_frame = pd.DataFrame(display_rows)
                human_columns = [
                    "published_at", "price_at_event", "return_15m_pct", "return_1h_pct",
                    "return_4h_pct", "return_24h_pct", "mfe_4h_pct", "mae_4h_pct", "status", "error",
                ]
                technical_columns = ["contract_symbol", "contract_uic", "candidate_event_id"]
                st.dataframe(
                    reaction_frame,
                    hide_index=True,
                    use_container_width=True,
                    column_order=tuple(column for column in human_columns + technical_columns if column in reaction_frame.columns),
                    column_config={
                        "published_at": st.column_config.TextColumn("Tidspunkt", width="small"),
                        "price_at_event": st.column_config.NumberColumn("Startpris", format="%.3f"),
                        "return_15m_pct": st.column_config.NumberColumn("+15m %", format="%.3f"),
                        "return_1h_pct": st.column_config.NumberColumn("+1t %", format="%.3f"),
                        "return_4h_pct": st.column_config.NumberColumn("+4t %", format="%.3f"),
                        "return_24h_pct": st.column_config.NumberColumn("+24t %", format="%.3f"),
                        "mfe_4h_pct": st.column_config.NumberColumn("MFE 4t %", format="%.3f"),
                        "mae_4h_pct": st.column_config.NumberColumn("MAE 4t %", format="%.3f"),
                        "status": "Status",
                        "error": "Feil",
                        "contract_symbol": "Kontrakt",
                        "contract_uic": "UIC",
                        "candidate_event_id": st.column_config.TextColumn("Teknisk hendelses-ID", width="medium"),
                    },
                )

                st.subheader("Historisk motor · prisvurdering")
                if not semantic_ready:
                    st.warning(
                        "Prisretning vises ikke før semantisk rangering er kjørt. Ufiltrerte GDELT-kandidater "
                        "kan ellers gi et misvisende signal."
                    )
                else:
                    selection = select_reactions_for_ranked_analogues(reaction_rows, semantic_rows)
                    st.write(
                        f"Semantisk valgte analoger: **{selection.selected_count}** · "
                        f"ekskludert: **{selection.excluded_count}**"
                    )
                    if selection.selected_count == 0:
                        st.warning(
                            "Ingen kandidater bestod den semantiske filtreringen. Historisk motor gir derfor "
                            "ikke en prisretning for denne hendelsen."
                        )
                    else:
                        assessment = build_historical_assessment(
                            selection.selected_reactions,
                            source_search_id=summary["search_id"],
                            asset="Brent",
                            semantic_filter_applied=True,
                        )
                        assessment_record = assessment.to_record()
                        st.caption(
                            "Primærhorisont: 4 timer. Bare semantisk relevante kandidater inngår. "
                            "Konflikt- og markedsregime er ennå ikke filtrert."
                        )
                        if assessment.independent_analogues < 3:
                            st.warning(
                                "Færre enn tre uavhengige analoger gjenstår. Retningen vises som et svakt "
                                "historisk hint, ikke som et robust signal."
                            )

                        render_historical_assessment(assessment)

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
