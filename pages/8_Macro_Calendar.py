from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import streamlit as st

from build_info import render_build_badge
from macro_calendar import calendar_rows, load_macro_calendar


st.set_page_config(page_title="Makrokalender · PriceGauger", page_icon="🗓️", layout="wide")
render_build_badge()
st.title("Makrokalender")
st.caption(
    "Kommende planlagte makro- og energipublikasjoner fra offisielle primærkilder. "
    "Foreløpig er modulen kun observasjon: hendelsene påvirker ikke anbefalingskort eller Decision State."
)

horizon = st.select_slider(
    "Vis kommende",
    options=(14, 30, 60, 90, 180),
    value=90,
    format_func=lambda days: f"{days} dager",
)


@st.cache_data(ttl=900, show_spinner=False)
def _load(days: int):
    result = load_macro_calendar(now=datetime.now(timezone.utc), horizon_days=days)
    return calendar_rows(result.events), result.source_errors


with st.spinner("Henter offisielle publiseringskalendere …"):
    rows, source_errors = _load(horizon)

if source_errors:
    st.warning(
        "Noen kilder kunne ikke oppdateres. Tabellen viser fortsatt hendelser fra kildene som svarte.\n\n"
        + "\n".join(f"- {item}" for item in source_errors)
    )

if not rows:
    st.info("Ingen kommende hendelser ble funnet i valgt periode.")
else:
    frame = pd.DataFrame(rows)
    st.dataframe(
        frame,
        hide_index=True,
        use_container_width=True,
        column_config={
            "Dato": st.column_config.TextColumn("Dato", width="small"),
            "Klokkeslett": st.column_config.TextColumn("Klokkeslett (Oslo)", width="small"),
            "Hendelse": st.column_config.TextColumn("Hendelse", width="large"),
            "Viktighet": st.column_config.TextColumn("Viktighet", width="small"),
            "Markeder": st.column_config.TextColumn("Relevante markeder", width="medium"),
            "Kilde": st.column_config.TextColumn("Kilde", width="small"),
            "Lenke": st.column_config.LinkColumn("Offisiell side", display_text="Åpne"),
        },
    )
    st.caption(
        "Tidene konverteres til Europe/Oslo. BLS/BEA/Fed hentes fra offisielle publiseringskalendere; "
        "EIA-radene følger den ordinære ukerytmen og lenker til EIA-siden der helligdagsavvik publiseres."
    )

st.divider()
st.subheader("Avgrensning i denne versjonen")
st.write(
    "Kalenderen samler og viser planlagte hendelser. Den leser ennå ikke actual/consensus, "
    "lager ikke spesialanalyse rundt publiseringstidspunktet og endrer ikke PriceGaugers prognoser. "
    "Dette kobles først på etter at dagens forecast/outcome-kjede er observert og validert."
)
