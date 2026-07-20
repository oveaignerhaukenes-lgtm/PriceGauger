from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from config import gdelt_api_key
from event_models import market_event_from_gdelt
from event_reactions import calculate_reactions
from gdelt_client import GdeltClient, GdeltError
from intraday_reactions import calculate_intraday_reactions
from storage import save_events, save_intraday_reactions, save_reactions
from timestamp_enrichment import enrich_event_timestamps

REACTION_ASSETS = {
    "Brent": "BZ=F",
    "Silver": "SI=F",
    "Gold": "GC=F",
    "DXY": "DX-Y.NYB",
}


def _upgrade_legacy_events(events: list) -> list:
    upgraded = []
    changed = False
    for event in events:
        if hasattr(event, "published_at"):
            upgraded.append(event)
            continue
        raw = getattr(event, "raw", None)
        if isinstance(raw, dict):
            upgraded.append(market_event_from_gdelt(raw))
            changed = True
        else:
            upgraded.append(event)
    return upgraded if changed else events


def _pipeline_signature(
    *,
    start_date: date,
    end_date: date,
    search: str,
    country: str,
    domain: str,
    limit: int,
    assets: list[str],
) -> tuple:
    return (
        start_date.isoformat(),
        end_date.isoformat(),
        search.strip(),
        country.strip(),
        domain,
        int(limit),
        tuple(sorted(assets)),
    )


def _run_pipeline(
    *,
    key: str,
    start_date: date,
    end_date: date,
    search: str,
    country: str,
    domain: str,
    limit: int,
    selected_assets: list[str],
) -> None:
    assets = {name: REACTION_ASSETS[name] for name in selected_assets}

    with st.status("Kjører automatisk analysepipeline …", expanded=True) as status:
        try:
            st.write("1/5 Henter GDELT-hendelser …")
            page = GdeltClient(key).list_events(
                date_start=start_date.isoformat(),
                date_end=end_date.isoformat(),
                search=search.strip(),
                country=country.strip(),
                domain=domain,
                limit=limit,
            )
            events = page.events
            st.session_state.gdelt_events = events
            st.write(f"Fant {len(events)} hendelser.")

            if not events:
                st.session_state.gdelt_intraday_reactions = []
                st.session_state.gdelt_reactions = []
                status.update(label="Ingen hendelser for valgte filtre", state="complete", expanded=False)
                return

            st.write("2/5 Finner nøyaktige publiseringstidspunkter …")
            events = enrich_event_timestamps(events)
            st.session_state.gdelt_events = events
            precise_count = sum(bool(getattr(event, "published_at", None)) for event in events)
            st.write(f"Fant klokkeslett for {precise_count} av {len(events)} hendelser.")

            st.write("3/5 Kobler hendelser til intradagpriser …")
            if precise_count and assets:
                intraday = calculate_intraday_reactions(events, assets)
            else:
                intraday = []
            st.session_state.gdelt_intraday_reactions = intraday
            st.write(f"Bygget {len(intraday)} intradagkoblinger.")

            st.write("4/5 Beregner daglige markedsreaksjoner …")
            reactions = calculate_reactions(events, assets) if assets else []
            st.session_state.gdelt_reactions = reactions
            st.write(f"Bygget {len(reactions)} dagskoblinger.")

            st.write("5/5 Lagrer analysegrunnlaget …")
            event_changes = save_events(events)
            intraday_changes = save_intraday_reactions(intraday) if intraday else 0
            reaction_changes = save_reactions(reactions) if reactions else 0
            st.session_state.gdelt_pipeline_summary = {
                "events": len(events),
                "precise": precise_count,
                "intraday": len(intraday),
                "daily": len(reactions),
                "saved": event_changes + intraday_changes + reaction_changes,
            }
            st.session_state.gdelt_pipeline_error = None
            status.update(label="Automatisk analysepipeline ferdig", state="complete", expanded=False)
        except (GdeltError, ValueError) as exc:
            st.session_state.gdelt_pipeline_error = f"GDELT-kallet mislyktes: {exc}"
            status.update(label="Pipelinen stoppet under GDELT-henting", state="error", expanded=True)
        except Exception as exc:
            st.session_state.gdelt_pipeline_error = f"Pipelinen mislyktes: {exc}"
            status.update(label="Den automatiske pipelinen mislyktes", state="error", expanded=True)


def render_event_lab() -> None:
    st.subheader("Historical Event Lab")
    st.caption(
        "Velg datointervall, søk og markeder. Henting, tidsberikelse, priskobling og lagring skjer automatisk når et filter endres."
    )

    key = gdelt_api_key()
    if not key:
        st.error("GDELT_CLOUD_API_KEY mangler i Streamlit Secrets.")
        return

    c1, c2 = st.columns(2)
    with c1:
        start_date = st.date_input("Fra dato", value=date.today() - timedelta(days=14), key="gdelt_start")
        search = st.text_input("Søk", value="attacks on energy infrastructure", key="gdelt_search")
        country = st.text_input("Land", placeholder="Iran", key="gdelt_country")
    with c2:
        end_date = st.date_input("Til dato", value=date.today(), key="gdelt_end")
        domain = st.selectbox(
            "Domene",
            ["", "POLITICAL", "ECONOMIC", "CORPORATE", "TECHNOLOGY", "INFRASTRUCTURE", "HEALTH", "INFORMATION", "ENVIRONMENT", "CRIME"],
            key="gdelt_domain",
        )
        limit = st.slider("Maks resultater", 5, 100, 50, 5, key="gdelt_limit")

    selected_assets = st.multiselect(
        "Markeder som skal analyseres automatisk",
        list(REACTION_ASSETS),
        default=list(REACTION_ASSETS),
        key="gdelt_pipeline_assets",
    )

    if start_date > end_date:
        st.error("Fra-dato må være før eller lik til-dato.")
        return
    if not search.strip():
        st.info("Skriv inn et søkeord for å starte den automatiske pipelinen.")
        return
    if not selected_assets:
        st.info("Velg minst ett marked for å starte den automatiske pipelinen.")
        return

    signature = _pipeline_signature(
        start_date=start_date,
        end_date=end_date,
        search=search,
        country=country,
        domain=domain,
        limit=limit,
        assets=selected_assets,
    )
    if st.session_state.get("gdelt_pipeline_signature") != signature:
        st.session_state.gdelt_pipeline_signature = signature
        st.session_state.pop("gdelt_pipeline_error", None)
        _run_pipeline(
            key=key,
            start_date=start_date,
            end_date=end_date,
            search=search,
            country=country,
            domain=domain,
            limit=limit,
            selected_assets=selected_assets,
        )

    pipeline_error = st.session_state.get("gdelt_pipeline_error")
    if pipeline_error:
        st.error(pipeline_error)

    summary = st.session_state.get("gdelt_pipeline_summary")
    if summary and not pipeline_error:
        p1, p2, p3, p4 = st.columns(4)
        p1.metric("Hendelser", summary["events"])
        p2.metric("Med klokkeslett", summary["precise"])
        p3.metric("Intradagkoblinger", summary["intraday"])
        p4.metric("Dagskoblinger", summary["daily"])

    events = _upgrade_legacy_events(st.session_state.get("gdelt_events", []))
    st.session_state.gdelt_events = events
    if not events:
        st.info("Ingen hendelser funnet for de valgte filtrene.")
        return

    records = []
    for event in events:
        record = event.to_record()
        raw = record.get("raw") if isinstance(record.get("raw"), dict) else {}
        record["timestamp_diagnostic"] = raw.get("_timestamp_diagnostic")
        record["source_article_url"] = raw.get("_timestamp_article_url")
        records.append(record)

    frame = pd.DataFrame(records)
    if "actors" in frame.columns:
        frame["actors"] = frame["actors"].apply(
            lambda values: ", ".join(values) if isinstance(values, list) else str(values or "")
        )
    visible = [
        "event_date", "published_at", "timestamp_source", "timestamp_confidence",
        "timestamp_diagnostic", "source_article_url", "title", "category", "domain",
        "country", "location", "actors", "confidence", "market_sensitivity",
        "significance", "url",
    ]
    st.dataframe(
        frame.reindex(columns=visible),
        use_container_width=True,
        hide_index=True,
        column_config={
            "published_at": st.column_config.DatetimeColumn("Publisert (UTC)"),
            "timestamp_source": "Tidskilde",
            "timestamp_confidence": st.column_config.NumberColumn("Tidssikkerhet", format="%.2f"),
            "timestamp_diagnostic": "Diagnose",
            "source_article_url": st.column_config.LinkColumn("Kildeartikkel"),
            "url": st.column_config.LinkColumn("GDELT-side"),
        },
    )
    st.download_button(
        "Last ned hendelser som CSV",
        frame.drop(columns=["raw"], errors="ignore").to_csv(index=False).encode("utf-8"),
        "gdelt_events.csv",
        "text/csv",
        use_container_width=True,
    )

    st.divider()
    st.subheader("Intradag: nyhet → pris")
    intraday = st.session_state.get("gdelt_intraday_reactions", [])
    precise_count = sum(bool(getattr(event, "published_at", None)) for event in events)
    st.caption(
        f"{precise_count} av {len(events)} hendelser kunne kobles til intradagkurser. "
        "Vinduene måles fra første omsettelige prisbar."
    )

    if intraday:
        intraday_frame = pd.DataFrame([reaction.to_record() for reaction in intraday])
        intraday_cols = [
            "event_title", "published_at", "asset", "interval", "market_state",
            "anchor_time", "anchor_lag_minutes", "quality_score", "duplicate_group_size",
            "distinct_window_bars", "base_price", "return_5m_pct", "bar_time_5m",
            "return_15m_pct", "bar_time_15m", "return_30m_pct", "bar_time_30m",
            "return_1h_pct", "bar_time_1h", "return_4h_pct", "bar_time_4h",
            "return_24h_pct", "bar_time_24h", "max_up_24h_pct", "max_down_24h_pct",
            "time_to_max_minutes", "time_to_min_minutes",
        ]
        st.dataframe(
            intraday_frame.reindex(columns=intraday_cols),
            use_container_width=True,
            hide_index=True,
            column_config={
                "event_title": "Hendelse",
                "published_at": st.column_config.DatetimeColumn("Publisert UTC"),
                "anchor_time": st.column_config.DatetimeColumn("Første prisbar UTC"),
                "anchor_lag_minutes": st.column_config.NumberColumn("Ventetid min", format="%.1f"),
                "quality_score": st.column_config.NumberColumn("Kvalitet", format="%.1f"),
                "base_price": st.column_config.NumberColumn("Startkurs", format="%.4f"),
                "return_5m_pct": st.column_config.NumberColumn("+5m", format="%+.3f %%"),
                "return_15m_pct": st.column_config.NumberColumn("+15m", format="%+.3f %%"),
                "return_30m_pct": st.column_config.NumberColumn("+30m", format="%+.3f %%"),
                "return_1h_pct": st.column_config.NumberColumn("+1t", format="%+.3f %%"),
                "return_4h_pct": st.column_config.NumberColumn("+4t", format="%+.3f %%"),
                "return_24h_pct": st.column_config.NumberColumn("+24t", format="%+.3f %%"),
                "max_up_24h_pct": st.column_config.NumberColumn("Maks opp 24t", format="%+.3f %%"),
                "max_down_24h_pct": st.column_config.NumberColumn("Maks ned 24t", format="%+.3f %%"),
            },
        )

        quality_summary = intraday_frame.groupby("asset", as_index=False).agg(
            koblinger=("event_id", "count"),
            snitt_kvalitet=("quality_score", "mean"),
            marked_apent=("market_state", lambda s: int((s == "open").sum())),
            duplikatgrupper=("duplicate_group_size", lambda s: int((s > 1).sum())),
            snitt_15m=("return_15m_pct", "mean"),
            median_1h=("return_1h_pct", "median"),
            andel_opp_1h=("return_1h_pct", lambda s: float((s > 0).mean() * 100)),
            snitt_24h=("return_24h_pct", "mean"),
            snitt_ventetid_min=("anchor_lag_minutes", "mean"),
        )
        st.subheader("Intradagoppsummering og datakvalitet")
        st.dataframe(quality_summary, use_container_width=True, hide_index=True)
        st.download_button(
            "Last ned intradagreaksjoner som CSV",
            intraday_frame.to_csv(index=False).encode("utf-8"),
            "event_intraday_reactions.csv",
            "text/csv",
            use_container_width=True,
        )
    else:
        st.info("Ingen intradagkoblinger kunne beregnes for dette utvalget.")

    st.divider()
    st.subheader("Daglige markedsreaksjoner")
    reactions = st.session_state.get("gdelt_reactions", [])
    if not reactions:
        st.info("Ingen daglige markedsreaksjoner kunne beregnes for dette utvalget.")
        return

    reaction_frame = pd.DataFrame([reaction.to_record() for reaction in reactions])
    show_cols = [
        "event_date", "asset", "base_date", "base_close", "return_1d_pct",
        "return_3d_pct", "return_5d_pct", "max_up_5d_pct", "max_down_5d_pct",
    ]
    st.dataframe(reaction_frame.reindex(columns=show_cols), use_container_width=True, hide_index=True)

    daily_summary = reaction_frame.groupby("asset", as_index=False).agg(
        hendelser=("event_id", "count"),
        snitt_1d=("return_1d_pct", "mean"),
        median_1d=("return_1d_pct", "median"),
        andel_opp_1d=("return_1d_pct", lambda s: float((s > 0).mean() * 100)),
        snitt_5d=("return_5d_pct", "mean"),
    )
    st.subheader("Dagsoppsummering per marked")
    st.dataframe(daily_summary, use_container_width=True, hide_index=True)
    st.download_button(
        "Last ned dagsreaksjoner som CSV",
        reaction_frame.to_csv(index=False).encode("utf-8"),
        "event_market_reactions.csv",
        "text/csv",
        use_container_width=True,
    )
