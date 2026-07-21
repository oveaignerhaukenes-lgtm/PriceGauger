from __future__ import annotations

from datetime import date, timedelta
from math import exp, log

import pandas as pd
import streamlit as st

from config import gdelt_api_key
from event_dna import build_event_dna, build_market_profile
from event_reactions import calculate_reactions
from event_resolution import canonical_event_from_plan, rank_gdelt_analogues
from gdelt_client import GdeltClient, GdeltError
from intraday_reactions import calculate_intraday_reactions
from signal_aggregator import EventSignal
from signal_store import SignalStore
from storage import save_events, save_intraday_reactions, save_reactions
from telegram_query_builder import TelegramSearchPlan, fetch_latest_search_plan
from timestamp_enrichment import enrich_event_timestamps

REACTION_ASSETS = {
    "Brent": "BZ=F",
    "Silver": "SI=F",
    "Gold": "GC=F",
    "DXY": "DX-Y.NYB",
}


@st.cache_data(ttl=300, show_spinner=False)
def _latest_telegram_plan() -> TelegramSearchPlan | None:
    return fetch_latest_search_plan()


def _sync_telegram_plan() -> TelegramSearchPlan | None:
    try:
        plan = _latest_telegram_plan()
    except Exception as exc:
        st.session_state.telegram_query_error = str(exc)
        return None
    if plan is None:
        return None

    st.session_state.telegram_query_error = None
    if st.session_state.get("telegram_query_message_url") != plan.message_url:
        st.session_state.telegram_query_message_url = plan.message_url
        st.session_state.telegram_search_plan = plan.to_record()
        st.session_state.gdelt_search = plan.search
        st.session_state.gdelt_country = plan.country
        if plan.domain:
            st.session_state.gdelt_domain = plan.domain
        st.session_state.pop("gdelt_pipeline_signature", None)
    return plan


def _pipeline_signature(*, plan: TelegramSearchPlan, start_date: date, end_date: date, limit: int, assets: list[str]) -> tuple:
    return (
        plan.message_url,
        start_date.isoformat(),
        end_date.isoformat(),
        plan.search,
        plan.country,
        plan.domain,
        int(limit),
        tuple(sorted(assets)),
    )


def _persist_canonical_signals(canonical, matches, intraday, assets: list[str]) -> int:
    store = SignalStore()
    dna = build_event_dna(canonical.to_market_event())
    stored = 0
    now = pd.Timestamp.now(tz="UTC")
    published = pd.to_datetime(canonical.published_at, utc=True, errors="coerce")
    age_hours = max(0.0, (now - published).total_seconds() / 3600.0) if not pd.isna(published) else 0.0
    freshness = exp(-(log(2.0) / 6.0) * age_hours)

    for asset in assets:
        profile = build_market_profile(asset=asset, similar_events=matches, reactions=intraday)
        expected = profile.weighted_mean_4h_pct
        if expected is None:
            expected = profile.median_4h_pct
        direction = profile.direction if expected is not None else "NEUTRAL"
        evidence = "HIGH" if profile.sample_size >= 12 and profile.confidence_pct >= 75 else "MEDIUM" if profile.sample_size >= 5 else "INSUFFICIENT"
        analytical_weight = (profile.confidence_pct / 100.0) * dna.source_quality * max(0.15, dna.severity)
        signal_weight = analytical_weight * freshness
        contribution = signal_weight * (1.0 if direction == "LONG" else -1.0 if direction == "SHORT" else 0.0)
        store.add(
            EventSignal(
                event_id=canonical.event_id,
                title=canonical.title,
                published_at=canonical.published_at or now.isoformat(),
                event_type=canonical.event_type,
                target=canonical.target,
                direction=direction,
                confidence_pct=profile.confidence_pct,
                expected_move_pct=expected,
                evidence_grade=evidence,
                analogue_sample=profile.sample_size,
                effective_analogue_sample=profile.effective_sample_size,
                source_quality=dna.source_quality,
                severity=dna.severity,
                age_hours=round(age_hours, 3),
                freshness_weight=round(freshness, 6),
                signal_weight=round(signal_weight, 6),
                contribution=round(contribution, 6),
                asset=asset,
                half_life_hours=6.0,
                max_age_hours=24.0,
            )
        )
        stored += 1
    return stored


def _run_pipeline(*, key: str, plan: TelegramSearchPlan, start_date: date, end_date: date, limit: int, selected_assets: list[str]) -> None:
    assets = {name: REACTION_ASSETS[name] for name in selected_assets}
    canonical = canonical_event_from_plan(plan)
    canonical_market_event = canonical.to_market_event()

    with st.status("Kjører event-sentrisk analysepipeline …", expanded=True) as status:
        try:
            st.write("1/6 Henter GDELT-kandidater …")
            page = GdeltClient(key).list_events(
                date_start=start_date.isoformat(),
                date_end=end_date.isoformat(),
                search=plan.search,
                country=plan.country,
                domain=plan.domain,
                limit=limit,
            )
            candidates = page.events
            st.write(f"Fant {len(candidates)} kandidater.")

            st.write("2/6 Rangerer kandidater mot Telegram-hendelsen …")
            matches = rank_gdelt_analogues(canonical, candidates, limit=limit, minimum_score=0.20)
            analogue_events = [item.event for item in matches]
            st.session_state.canonical_telegram_event = canonical.to_record()
            st.session_state.gdelt_analogue_matches = [item.to_record() for item in matches]
            # Decision Lab expects one query event followed by historical candidates.
            # The first item is now always the canonical Telegram event, never a GDELT spin-off.
            st.session_state.gdelt_events = [canonical_market_event, *analogue_events]
            st.write(f"Beholdt {len(analogue_events)} rangerte analoger.")

            if not analogue_events:
                st.session_state.gdelt_intraday_reactions = []
                st.session_state.gdelt_reactions = []
                st.session_state.gdelt_pipeline_summary = {"analogues": 0, "precise": 0, "intraday": 0, "daily": 0, "signals": 0}
                status.update(label="Ingen tilstrekkelig like GDELT-analoger", state="complete", expanded=False)
                return

            st.write("3/6 Finner publiseringstidspunkter for analogene …")
            analogue_events = enrich_event_timestamps(analogue_events)
            precise_count = sum(bool(getattr(event, "published_at", None)) for event in analogue_events)
            st.session_state.gdelt_events = [canonical_market_event, *analogue_events]

            st.write("4/6 Kobler analogene til markedsreaksjoner …")
            intraday = calculate_intraday_reactions(analogue_events, assets) if precise_count and assets else []
            daily = calculate_reactions(analogue_events, assets) if assets else []
            st.session_state.gdelt_intraday_reactions = intraday
            st.session_state.gdelt_reactions = daily

            st.write("5/6 Lagrer historisk evidens …")
            event_changes = save_events(analogue_events)
            intraday_changes = save_intraday_reactions(intraday) if intraday else 0
            daily_changes = save_reactions(daily) if daily else 0

            st.write("6/6 Produserer kanoniske EventSignal-objekter …")
            signal_count = _persist_canonical_signals(canonical, matches, intraday, selected_assets)
            st.session_state.gdelt_pipeline_summary = {
                "analogues": len(analogue_events),
                "precise": precise_count,
                "intraday": len(intraday),
                "daily": len(daily),
                "signals": signal_count,
                "saved": event_changes + intraday_changes + daily_changes,
            }
            st.session_state.gdelt_pipeline_error = None
            status.update(label="Event-sentrisk analysepipeline ferdig", state="complete", expanded=False)
        except (GdeltError, ValueError) as exc:
            st.session_state.gdelt_pipeline_error = f"GDELT-kallet mislyktes: {exc}"
            status.update(label="Pipelinen stoppet under GDELT-henting", state="error", expanded=True)
        except Exception as exc:
            st.session_state.gdelt_pipeline_error = f"Pipelinen mislyktes: {exc}"
            status.update(label="Den event-sentriske pipelinen mislyktes", state="error", expanded=True)


def render_event_lab() -> None:
    st.subheader("Historical Event Lab")
    st.caption("Telegram er primærhendelsen. GDELT brukes kun som rangert historisk evidens for markedsprofil og score.")

    key = gdelt_api_key()
    if not key:
        st.error("GDELT_CLOUD_API_KEY mangler i Streamlit Secrets.")
        return

    plan = _sync_telegram_plan()
    error = st.session_state.get("telegram_query_error")
    if error:
        st.warning(f"Telegram kunne ikke oppdatere søket akkurat nå: {error}")
    if plan is None:
        st.info("Venter på en relevant Telegram-melding.")
        return

    with st.container(border=True):
        st.markdown("**Kanonisk Telegram-hendelse**")
        q1, q2, q3, q4 = st.columns(4)
        q1.metric("Hendelsestype", plan.event_type)
        q2.metric("Mål", plan.target)
        q3.metric("Land", plan.country or "Ukjent")
        q4.metric("Regime", plan.regime_id)
        st.write(plan.message_text)
        st.caption(f"GDELT-søk: {plan.search} · GDELT kan ikke endre identiteten eller EventDNA-et til denne hendelsen.")
        st.link_button("Åpne Telegram-meldingen", plan.message_url)

    c1, c2 = st.columns(2)
    with c1:
        start_date = st.date_input("Fra dato", value=date.today() - timedelta(days=14), key="gdelt_start")
    with c2:
        end_date = st.date_input("Til dato", value=date.today(), key="gdelt_end")
    limit = st.slider("Maks GDELT-kandidater", 5, 100, 50, 5, key="gdelt_limit")
    selected_assets = st.multiselect("Markeder", list(REACTION_ASSETS), default=list(REACTION_ASSETS), key="gdelt_pipeline_assets")

    if start_date > end_date:
        st.error("Fra-dato må være før eller lik til-dato.")
        return
    if not selected_assets:
        st.info("Velg minst ett marked.")
        return

    signature = _pipeline_signature(plan=plan, start_date=start_date, end_date=end_date, limit=limit, assets=selected_assets)
    if st.session_state.get("gdelt_pipeline_signature") != signature:
        st.session_state.gdelt_pipeline_signature = signature
        st.session_state.pop("gdelt_pipeline_error", None)
        _run_pipeline(key=key, plan=plan, start_date=start_date, end_date=end_date, limit=limit, selected_assets=selected_assets)

    pipeline_error = st.session_state.get("gdelt_pipeline_error")
    if pipeline_error:
        st.error(pipeline_error)
        return

    summary = st.session_state.get("gdelt_pipeline_summary")
    if summary:
        p1, p2, p3, p4, p5 = st.columns(5)
        p1.metric("Analoger", summary.get("analogues", 0))
        p2.metric("Med klokkeslett", summary.get("precise", 0))
        p3.metric("Intradag", summary.get("intraday", 0))
        p4.metric("Daglig", summary.get("daily", 0))
        p5.metric("EventSignal", summary.get("signals", 0))

    matches = st.session_state.get("gdelt_analogue_matches", [])
    st.markdown("### Rangerte GDELT-analoger")
    if not matches:
        st.info("Ingen analoger passerte likhetsterskelen.")
    else:
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
        st.dataframe(frame, use_container_width=True, hide_index=True, column_config={"likhet": st.column_config.NumberColumn("Likhet", format="%.1%%")})

    intraday = st.session_state.get("gdelt_intraday_reactions", [])
    st.markdown("### Analog → markedsreaksjon")
    if intraday:
        frame = pd.DataFrame([item.to_record() for item in intraday])
        st.dataframe(frame.reindex(columns=["event_title", "asset", "published_at", "quality_score", "return_1h_pct", "return_4h_pct", "return_24h_pct"]), use_container_width=True, hide_index=True)
    else:
        st.info("Ingen intradagreaksjoner tilgjengelig for analogutvalget.")
