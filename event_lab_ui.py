from __future__ import annotations

from datetime import date, timedelta
from math import exp, log

import pandas as pd
import streamlit as st

from config import gdelt_api_key
from event_dna import build_event_dna, build_market_profile
from event_reactions import calculate_reactions
from event_resolution import canonical_event_from_plan, rank_gdelt_analogues
from gdelt_bigquery import fetch_bigquery_events
from gdelt_client import GdeltClient
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
        "bigquery-first-v1",
    )


def _publish_canonical_event(plan: TelegramSearchPlan):
    canonical = canonical_event_from_plan(plan)
    canonical_market_event = canonical.to_market_event()
    st.session_state.canonical_telegram_event = canonical.to_record()
    st.session_state.canonical_market_event = canonical_market_event

    historical = [
        event
        for event in st.session_state.get("gdelt_events", [])
        if getattr(event, "event_id", None) != canonical_market_event.event_id
    ]
    st.session_state.gdelt_events = [canonical_market_event, *historical]
    return canonical, canonical_market_event


def _clear_historical_evidence(*, status: str, warning: str | None = None) -> None:
    canonical = st.session_state.get("canonical_market_event")
    st.session_state.gdelt_events = [canonical] if canonical is not None else []
    st.session_state.gdelt_analogue_matches = []
    st.session_state.gdelt_intraday_reactions = []
    st.session_state.gdelt_reactions = []
    st.session_state.gdelt_historical_status = status
    st.session_state.gdelt_pipeline_summary = {
        "status": status,
        "provider": "UNAVAILABLE",
        "analogues": 0,
        "precise": 0,
        "intraday": 0,
        "daily": 0,
        "signals": 0,
        "saved": 0,
    }
    st.session_state.gdelt_pipeline_error = warning


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
        evidence = (
            "HIGH" if profile.sample_size >= 12 and profile.confidence_pct >= 75
            else "MEDIUM" if profile.sample_size >= 5
            else "INSUFFICIENT"
        )
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


def _fetch_candidates(*, plan: TelegramSearchPlan, start_date: date, end_date: date, limit: int):
    """Use BigQuery as the canonical source; DOC API is only a bounded fallback."""
    try:
        page = fetch_bigquery_events(
            date_start=start_date,
            date_end=end_date,
            search=plan.search,
            country=plan.country,
            domain=plan.domain,
            event_type=plan.event_type,
            target=plan.target,
            limit=limit,
        )
        return page, "GDELT BigQuery", None
    except Exception as bigquery_error:
        key = gdelt_api_key()
        if not key:
            raise RuntimeError(f"BigQuery feilet og DOC fallback er ikke konfigurert: {bigquery_error}") from bigquery_error
        try:
            page = GdeltClient(key).list_events(
                date_start=start_date.isoformat(),
                date_end=end_date.isoformat(),
                search=plan.search,
                country=plan.country,
                domain=plan.domain,
                limit=limit,
            )
            warning = f"BigQuery var utilgjengelig; brukte GDELT DOC fallback. BigQuery-feil: {bigquery_error}"
            if page.warning:
                warning += f" · DOC: {page.warning}"
            return page, "GDELT DOC fallback", warning
        except Exception as doc_error:
            raise RuntimeError(
                f"BigQuery feilet ({bigquery_error}); DOC fallback feilet også ({doc_error})"
            ) from doc_error


def _run_pipeline(*, plan: TelegramSearchPlan, start_date: date, end_date: date, limit: int, selected_assets: list[str]) -> None:
    assets = {name: REACTION_ASSETS[name] for name in selected_assets}
    canonical, canonical_market_event = _publish_canonical_event(plan)
    st.session_state.gdelt_historical_status = "PENDING"

    with st.status("Kjører event-sentrisk analysepipeline …", expanded=True) as status:
        try:
            st.write("1/6 Henter historiske GDELT-kandidater fra BigQuery …")
            page, provider, provider_warning = _fetch_candidates(
                plan=plan,
                start_date=start_date,
                end_date=end_date,
                limit=limit,
            )
            candidates = page.events
            st.write(f"Fant {len(candidates)} kandidater via {provider}.")

            st.write("2/6 Rangerer kandidater mot Telegram-hendelsen …")
            matches = rank_gdelt_analogues(canonical, candidates, limit=limit, minimum_score=0.20)
            analogue_events = [item.event for item in matches]
            st.session_state.gdelt_analogue_matches = [item.to_record() for item in matches]
            st.session_state.gdelt_events = [canonical_market_event, *analogue_events]
            st.write(f"Beholdt {len(analogue_events)} rangerte analoger.")

            if not analogue_events:
                _clear_historical_evidence(status="AVAILABLE_NO_MATCHES", warning=provider_warning or page.warning)
                st.session_state.gdelt_pipeline_summary["provider"] = provider
                status.update(label="Ingen tilstrekkelig like GDELT-analoger", state="complete", expanded=False)
                return

            st.write("3/6 Sikrer publiseringstidspunkter for analogene …")
            missing_timestamps = [event for event in analogue_events if not getattr(event, "published_at", None)]
            if missing_timestamps:
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

            st.write("6/6 Produserer EventSignal-bidrag til Signalaggregat …")
            signal_count = _persist_canonical_signals(canonical, matches, intraday, selected_assets)
            st.session_state.gdelt_historical_status = "AVAILABLE"
            st.session_state.gdelt_pipeline_summary = {
                "status": "AVAILABLE",
                "provider": provider,
                "analogues": len(analogue_events),
                "precise": precise_count,
                "intraday": len(intraday),
                "daily": len(daily),
                "signals": signal_count,
                "saved": event_changes + intraday_changes + daily_changes,
                "bytes_processed": getattr(page, "bytes_processed", 0),
            }
            st.session_state.gdelt_pipeline_error = provider_warning or page.warning
            status.update(label=f"Historisk pipeline ferdig via {provider}", state="complete", expanded=False)
        except Exception as exc:
            warning = f"Historisk GDELT-evidens er utilgjengelig: {exc}"
            _clear_historical_evidence(status="UNAVAILABLE", warning=warning)
            status.update(label="Historikk utilgjengelig – Direct/Decision fortsetter", state="complete", expanded=False)


def render_event_lab() -> None:
    st.subheader("Historical Event Lab")
    st.caption("BigQuery er primærkilden. DOC API brukes bare som fallback. Ferdige historiske reaksjoner blir EventSignal-bidrag i Signalaggregat.")

    plan = _sync_telegram_plan()
    error = st.session_state.get("telegram_query_error")
    if error:
        st.warning(f"Telegram kunne ikke oppdatere søket akkurat nå: {error}")
    if plan is None:
        st.info("Venter på en relevant Telegram-melding.")
        return

    _publish_canonical_event(plan)
    with st.container(border=True):
        st.markdown("**Kanonisk Telegram-hendelse**")
        q1, q2, q3, q4 = st.columns(4)
        q1.metric("Hendelsestype", plan.event_type)
        q2.metric("Mål", plan.target)
        q3.metric("Land", plan.country or "Ukjent")
        q4.metric("Regime", plan.regime_id)
        st.write(plan.message_text)
        st.caption(f"Historisk søk: {plan.search} · BigQuery kan ikke endre identiteten eller EventDNA-et til hendelsen.")
        st.link_button("Åpne Telegram-meldingen", plan.message_url)

    c1, c2 = st.columns(2)
    with c1:
        start_date = st.date_input("Fra dato", value=date.today() - timedelta(days=30), key="gdelt_start")
    with c2:
        end_date = st.date_input("Til dato", value=date.today(), key="gdelt_end")
    limit = st.slider("Maks GDELT-kandidater", 5, 100, 50, 5, key="gdelt_limit")
    selected_assets = st.multiselect(
        "Markeder",
        list(REACTION_ASSETS),
        default=list(REACTION_ASSETS),
        key="gdelt_pipeline_assets",
    )

    if start_date > end_date:
        st.error("Fra-dato må være før eller lik til-dato.")
        return
    if not selected_assets:
        st.info("Velg minst ett marked.")
        return

    signature = _pipeline_signature(
        plan=plan,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        assets=selected_assets,
    )
    if st.session_state.get("gdelt_pipeline_signature") != signature:
        st.session_state.gdelt_pipeline_signature = signature
        st.session_state.pop("gdelt_pipeline_error", None)
        _run_pipeline(
            plan=plan,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            selected_assets=selected_assets,
        )

    historical_status = st.session_state.get("gdelt_historical_status", "NOT_ANALYSED")
    pipeline_error = st.session_state.get("gdelt_pipeline_error")
    if pipeline_error:
        st.warning(pipeline_error)

    summary = st.session_state.get("gdelt_pipeline_summary") or {}
    provider = summary.get("provider", "IKKE KJØRT")
    st.caption(
        f"Historisk evidensstatus: {historical_status} · Kilde: {provider} · "
        "Decision Lab beholder den kanoniske hendelsen uansett historikkstatus."
    )

    if summary:
        p1, p2, p3, p4, p5, p6 = st.columns(6)
        p1.metric("Kilde", provider)
        p2.metric("Analoger", summary.get("analogues", 0))
        p3.metric("Med klokkeslett", summary.get("precise", 0))
        p4.metric("Intradag", summary.get("intraday", 0))
        p5.metric("Daglig", summary.get("daily", 0))
        p6.metric("EventSignal", summary.get("signals", 0))

    matches = st.session_state.get("gdelt_analogue_matches", [])
    st.markdown("### Rangerte GDELT-analoger")
    if not matches:
        if historical_status == "UNAVAILABLE":
            st.info("Historiske analoger ble ikke undersøkt fordi både BigQuery og eventuell DOC fallback var utilgjengelig.")
        elif historical_status == "DEGRADED":
            st.info("Historikkberikelsen ble bare delvis gjennomført.")
        else:
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
        st.dataframe(
            frame,
            use_container_width=True,
            hide_index=True,
            column_config={"likhet": st.column_config.NumberColumn("Likhet", format="%.1%%")},
        )

    intraday = st.session_state.get("gdelt_intraday_reactions", [])
    st.markdown("### Analog → markedsreaksjon")
    if intraday:
        frame = pd.DataFrame([item.to_record() for item in intraday])
        st.dataframe(
            frame.reindex(columns=[
                "event_title", "asset", "published_at", "quality_score",
                "return_1h_pct", "return_4h_pct", "return_24h_pct",
            ]),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("Ingen intradagreaksjoner tilgjengelig for analogutvalget.")
