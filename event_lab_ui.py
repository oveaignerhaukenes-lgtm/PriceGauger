from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from config import gdelt_api_key
from event_models import market_event_from_gdelt
from event_reactions import calculate_reactions
from gdelt_client import GdeltClient, GdeltError
from storage import save_events, save_reactions
from timestamp_enrichment import enrich_event_timestamps

REACTION_ASSETS = {
    "Brent": "BZ=F",
    "Silver": "SI=F",
    "Gold": "GC=F",
    "DXY": "DX-Y.NYB",
}


def _upgrade_legacy_events(events: list) -> list:
    """Rebuild events kept in Streamlit session state before timestamp fields existed."""
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


def render_event_lab() -> None:
    st.subheader("Historical Event Lab")
    st.caption(
        "Mekanisk innsamling og filtrering først. Deretter berikes hendelsene med publiseringstid og kobles til markedsreaksjoner."
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

    if start_date > end_date:
        st.error("Fra-dato må være før eller lik til-dato.")
        return

    if st.button("Hent GDELT-hendelser", type="primary", use_container_width=True):
        try:
            page = GdeltClient(key).list_events(
                date_start=start_date.isoformat(),
                date_end=end_date.isoformat(),
                search=search.strip(),
                country=country.strip(),
                domain=domain,
                limit=limit,
            )
            st.session_state.gdelt_events = page.events
            st.session_state.pop("gdelt_reactions", None)
        except (GdeltError, ValueError) as exc:
            st.error(f"GDELT-kallet mislyktes: {exc}")
        except Exception:
            st.error("Uventet feil under GDELT-kallet. Nøkkel og request-detaljer er skjult.")

    events = st.session_state.get("gdelt_events", [])
    if not events:
        st.info("Velg filtre og trykk «Hent GDELT-hendelser».")
        return

    events = _upgrade_legacy_events(events)
    st.session_state.gdelt_events = events

    if st.button("Finn nøyaktige publiseringstidspunkter", use_container_width=True):
        try:
            with st.spinner("Leser GDELTs kildeartikler og publiseringsmetadata …"):
                st.session_state.gdelt_events = enrich_event_timestamps(events)
            events = st.session_state.gdelt_events
            precise = sum(bool(getattr(event, "published_at", None)) for event in events)
            st.success(f"Fant klokkeslett for {precise} av {len(events)} hendelser.")
        except Exception as exc:
            st.error(f"Kunne ikke berike tidsstemplene: {exc}")

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
    display_frame = frame.reindex(columns=visible)
    st.dataframe(
        display_frame,
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

    a, b = st.columns(2)
    with a:
        st.download_button(
            "Last ned hendelser som CSV",
            frame.drop(columns=["raw"], errors="ignore").to_csv(index=False).encode("utf-8"),
            "gdelt_events.csv",
            "text/csv",
            use_container_width=True,
        )
    with b:
        if st.button("Lagre hendelser i lokal database", use_container_width=True):
            changed = save_events(events)
            st.success(f"Hendelsesdatabasen ble oppdatert ({changed} innsettinger/oppdateringer).")

    st.divider()
    st.subheader("Historiske markedsreaksjoner")
    precise_count = sum(bool(getattr(event, "published_at", None)) for event in events)
    st.caption(
        f"{precise_count} av {len(events)} hendelser har nå et presist publiseringstidspunkt. "
        "Denne reaksjonsvisningen bruker fortsatt dagskurser; 5-minuttersmotoren kobles på som neste trinn."
    )

    selected_assets = st.multiselect(
        "Markeder", list(REACTION_ASSETS), default=list(REACTION_ASSETS), key="reaction_assets"
    )
    if st.button("Beregn markedsreaksjoner", use_container_width=True):
        if not selected_assets:
            st.warning("Velg minst ett marked.")
        else:
            try:
                with st.spinner("Henter historiske priser og kobler dem til hendelsene …"):
                    assets = {name: REACTION_ASSETS[name] for name in selected_assets}
                    reactions = calculate_reactions(events, assets)
                st.session_state.gdelt_reactions = reactions
                st.success(f"Beregnet {len(reactions)} hendelse–marked-koblinger.")
            except Exception as exc:
                st.error(f"Kunne ikke beregne markedsreaksjoner: {exc}")

    reactions = st.session_state.get("gdelt_reactions", [])
    if not reactions:
        return

    reaction_frame = pd.DataFrame([reaction.to_record() for reaction in reactions])
    show_cols = [
        "event_date", "asset", "base_date", "base_close", "return_1d_pct",
        "return_3d_pct", "return_5d_pct", "max_up_5d_pct", "max_down_5d_pct",
    ]
    st.dataframe(
        reaction_frame.reindex(columns=show_cols),
        use_container_width=True,
        hide_index=True,
        column_config={
            "base_close": st.column_config.NumberColumn("Startkurs", format="%.3f"),
            "return_1d_pct": st.column_config.NumberColumn("+1d", format="%+.2f %%"),
            "return_3d_pct": st.column_config.NumberColumn("+3d", format="%+.2f %%"),
            "return_5d_pct": st.column_config.NumberColumn("+5d", format="%+.2f %%"),
            "max_up_5d_pct": st.column_config.NumberColumn("Maks opp 5d", format="%+.2f %%"),
            "max_down_5d_pct": st.column_config.NumberColumn("Maks ned 5d", format="%+.2f %%"),
        },
    )

    summary = reaction_frame.groupby("asset", as_index=False).agg(
        hendelser=("event_id", "count"),
        snitt_1d=("return_1d_pct", "mean"),
        median_1d=("return_1d_pct", "median"),
        andel_opp_1d=("return_1d_pct", lambda s: float((s > 0).mean() * 100)),
        snitt_5d=("return_5d_pct", "mean"),
    )
    st.subheader("Oppsummering per marked")
    st.dataframe(summary, use_container_width=True, hide_index=True)

    c1, c2 = st.columns(2)
    with c1:
        st.download_button(
            "Last ned reaksjoner som CSV",
            reaction_frame.to_csv(index=False).encode("utf-8"),
            "event_market_reactions.csv",
            "text/csv",
            use_container_width=True,
        )
    with c2:
        if st.button("Lagre reaksjoner i lokal database", use_container_width=True):
            event_changes = save_events(events)
            reaction_changes = save_reactions(reactions)
            st.success(f"Lagret hendelser ({event_changes}) og reaksjoner ({reaction_changes}) i databasen.")
