from __future__ import annotations

from dataclasses import replace
import json

import pandas as pd
import streamlit as st

from engine_sidebar import render_engine_sidebar
from historical_engine_ui import compact_timestamp
from telegram_channel_store import TelegramChannelStore, telegram_message_key
from telegram_flow_engine import OpenAITelegramFlowScorer, aggregate_scored_posts
from telegram_flow_store import TelegramFlowStore
from telegram_query_builder import fetch_search_plans


st.set_page_config(page_title="Telegram Flow", page_icon="📡", layout="wide")
st.title("📡 Telegram Flow")
st.caption(
    "Valgte Telegram-kanaler fungerer som den primære informasjonsstrømmen. Hver post scores semantisk "
    "per marked, hendelser grupperes for å hindre dobbelttelling, og bidragene summeres med tidsvekting."
)
render_engine_sidebar(active="telegram_flow")

channel_store = TelegramChannelStore()

with st.sidebar:
    st.header("Telegram-kilder")
    active_channels = channel_store.list_enabled()
    st.caption("Aktive: " + (", ".join(f"@{item}" for item in active_channels) if active_channels else "ingen"))

    new_channel = st.text_input(
        "Legg til kanal",
        placeholder="@kanal eller https://t.me/kanal",
        help="Lagres i databasen og plukkes opp av workeren i neste syklus.",
    )
    if st.button("Legg til kanal", use_container_width=True):
        try:
            added = channel_store.add(new_channel)
            st.success(f"@{added} lagt til.")
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))

    removable = st.multiselect(
        "Trekk fra kanaler",
        options=active_channels,
        format_func=lambda value: f"@{value}",
        help="Historiske poster beholdes for revisjon; kanalen slutter bare å bli hentet inn fremover.",
    )
    if st.button("Fjern valgte", use_container_width=True, disabled=not removable):
        remaining = [item for item in active_channels if item not in removable]
        if not remaining:
            st.error("Minst én Telegram-kanal må være aktiv.")
        else:
            for channel in removable:
                channel_store.disable(channel)
            st.success("Kanalvalg oppdatert.")
            st.rerun()

    st.divider()
    st.header("Valgt informasjonsbias")
    posts_per_channel = st.number_input("Nyeste poster per kanal", min_value=2, max_value=20, value=8)
    half_life_hours = st.number_input("Halveringstid for signal", min_value=0.5, max_value=48.0, value=4.0, step=0.5)
    minimum_signal = st.number_input("Minste regelsignal ved innhenting", min_value=1, max_value=3, value=1)
    run = st.button("Kjør ny vurdering nå", type="primary", use_container_width=True)

store = TelegramFlowStore()
state_key = "telegram_flow_latest"

if state_key not in st.session_state:
    persisted = store.load_latest_snapshot()
    if persisted is not None:
        st.session_state[state_key] = {
            "assessment": persisted,
            "scored": [],
            "model": persisted.model,
            "source": "worker/database",
        }

if run:
    channels = channel_store.list_enabled()
    if not channels:
        st.error("Legg inn minst én Telegram-kanal.")
    else:
        try:
            collected = []
            weights = {}
            with st.spinner("Henter poster fra valgte kanaler …"):
                for channel in channels:
                    plans = fetch_search_plans(channel, minimum_signal=int(minimum_signal), timeout=45)
                    for plan in plans[-int(posts_per_channel):]:
                        collected.append(
                            (
                                channel,
                                replace(
                                    plan,
                                    message_id=telegram_message_key(channel, plan.message_id),
                                ),
                            )
                        )
                    weights[channel] = 1.0
            collected.sort(key=lambda item: item[1].published_at)
            if not collected:
                st.warning("Ingen relevante poster ble hentet fra kanalene.")
            else:
                scorer = OpenAITelegramFlowScorer()
                with st.spinner("AI scorer markedsvirkningen i hver post og grupperer samme hendelse …"):
                    scored = scorer.score(collected)
                    store.save_posts(scored)
                    assessment = aggregate_scored_posts(
                        store.load_posts(limit=500),
                        channel_weights=weights,
                        half_life_hours=float(half_life_hours),
                    )
                    store.save_snapshot(assessment)
                st.session_state[state_key] = {
                    "assessment": assessment,
                    "scored": scored,
                    "model": scorer.model,
                    "source": "manual/database",
                }
        except Exception as exc:
            st.error(f"Telegram Flow kunne ikke fullføres: {exc}")

result = st.session_state.get(state_key)
if result is None:
    st.info("Ingen lagret Telegram Flow-vurdering finnes ennå. Workeren bygger den automatisk når nye poster behandles.")
else:
    assessment = result["assessment"]
    st.caption(
        f"Kilde: {result.get('source', 'ukjent')} · modell: {result['model']} · poster: {assessment.post_count} · "
        f"hendelsesklynger: {assessment.event_cluster_count} · oppdatert: {compact_timestamp(assessment.as_of)}"
    )

    st.subheader("Fortløpende markedsbias")
    assets = list(assessment.assets)
    for start in range(0, len(assets), 2):
        columns = st.columns(2)
        for column, item in zip(columns, assets[start:start + 2]):
            with column:
                with st.container(border=True):
                    st.markdown(f"### {item.asset}")
                    st.markdown(f"**{item.direction}**")
                    st.write(f"Flow-score: **{item.flow_score:+.3f}**")
                    st.write(f"Normalisert retning: **{item.normalized_score:+.2f}**")
                    st.write(f"Confidence: **{item.confidence * 100:.0f} %**")
                    st.caption(
                        f"Bullish hendelser: {item.bullish_events} · bearish: {item.bearish_events} · "
                        f"valgte hendelser: {item.selected_event_count}"
                    )
                    if item.top_drivers:
                        st.markdown("**Sterkeste drivere**")
                        for driver in item.top_drivers:
                            st.write(driver)

    st.subheader("Alle postbidrag")
    st.caption("Bare én hovedpost per semantisk hendelsesklynge og marked inngår i summen. Hele teksten vises under tabellen.")
    rows = [item.to_record() for item in assessment.contributions]
    if rows:
        frame = pd.DataFrame(rows)
        frame["published_at"] = frame["published_at"].map(compact_timestamp)
        display = frame[
            [
                "selected", "asset", "raw_score", "channel", "published_at", "event_key",
                "direction", "impact", "confidence", "decay", "novelty", "source_quality", "rationale",
            ]
        ]
        st.dataframe(
            display,
            hide_index=True,
            use_container_width=True,
            row_height=62,
            column_config={
                "selected": st.column_config.CheckboxColumn("Teller"),
                "asset": "Marked",
                "raw_score": st.column_config.NumberColumn("Bidrag", format="%+.3f"),
                "channel": st.column_config.TextColumn("Kanal", width="medium"),
                "published_at": st.column_config.TextColumn("Tidspunkt", width="small"),
                "event_key": st.column_config.TextColumn("Hendelsesklynge", width="large"),
                "direction": st.column_config.NumberColumn("Retning", format="%+.2f"),
                "impact": st.column_config.NumberColumn("Impact", format="%.2f"),
                "confidence": st.column_config.NumberColumn("Confidence", format="%.2f"),
                "decay": st.column_config.NumberColumn("Tidsvekt", format="%.2f"),
                "novelty": st.column_config.NumberColumn("Nyhet", format="%.2f"),
                "source_quality": st.column_config.NumberColumn("Kilde", format="%.2f"),
                "rationale": st.column_config.TextColumn("Kausal begrunnelse", width="large"),
            },
        )

        with st.expander("Full begrunnelse per tellende bidrag", expanded=False):
            for item in assessment.contributions:
                if not item.selected:
                    continue
                st.markdown(f"**{item.asset} · {item.raw_score:+.3f} · {item.channel} · {item.event_key}**")
                st.write(item.rationale)
                st.caption(compact_timestamp(item.published_at))

    with st.expander("Strukturert output"):
        record = assessment.to_record()
        st.json(record)
        st.download_button(
            "Last ned Telegram Flow som JSON",
            data=json.dumps(record, ensure_ascii=False, indent=2),
            file_name="telegram_flow_assessment.json",
            mime="application/json",
            use_container_width=True,
        )
