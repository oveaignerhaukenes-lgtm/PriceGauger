from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from config import gdelt_api_key
from gdelt_client import GdeltClient, GdeltError
from storage import save_events

st.set_page_config(page_title="Historical Event Lab", page_icon="🧭", layout="wide")
st.title("🧭 Historical Event Lab")
st.caption("Mekanisk innsamling og filtrering først. Semantisk AI-vurdering kobles på etter at datasettet er ryddig og etterprøvbart.")

api_key = gdelt_api_key()
if not api_key:
    st.error("GDELT_CLOUD_API_KEY mangler i Streamlit Secrets.")
    st.stop()

with st.sidebar:
    st.header("GDELT-søk")
    end_date = st.date_input("Til dato", value=date.today())
    start_date = st.date_input("Fra dato", value=end_date - timedelta(days=14))
    search = st.text_input("Semantisk søk", value="attacks on energy infrastructure")
    country = st.text_input("Land", placeholder="Iran")
    category = st.text_input("Kategori", placeholder="Protests eller CRIME")
    domain = st.selectbox(
        "Domene",
        ["", "POLITICAL", "ECONOMIC", "CORPORATE", "TECHNOLOGY", "INFRASTRUCTURE", "HEALTH", "INFORMATION", "ENVIRONMENT", "CRIME"],
    )
    event_family = st.selectbox("Hendelsesfamilie", ["", "conflict", "cameoplus"])
    confidence_profile = st.selectbox("Kvalitetsprofil", ["strictest", "precise", "balanced", "loose"], index=1)
    sort = st.selectbox("Sortering", ["significance", "recent"])
    limit = st.slider("Maks resultater", 5, 100, 50, 5)
    run_search = st.button("Hent hendelser", type="primary", use_container_width=True)

if start_date > end_date:
    st.error("Fra-dato må være før eller lik til-dato.")
    st.stop()

if "gdelt_events" not in st.session_state:
    st.session_state.gdelt_events = []

if run_search:
    try:
        client = GdeltClient(api_key)
        with st.spinner("Henter strukturerte hendelser fra GDELT Cloud …"):
            page = client.list_events(
                date_start=start_date.isoformat(),
                date_end=end_date.isoformat(),
                search=search.strip(),
                country=country.strip(),
                category=category.strip(),
                domain=domain,
                event_family=event_family,
                confidence_profile=confidence_profile,
                sort=sort,
                limit=limit,
            )
        st.session_state.gdelt_events = page.events
        st.session_state.gdelt_next_cursor = page.next_cursor
    except (GdeltError, ValueError) as exc:
        st.error(f"GDELT-kallet mislyktes: {exc}")
    except Exception:
        st.error("Uventet feil under GDELT-kallet. Nøkkelen og request-detaljene er skjult.")

records = [event.to_record() for event in st.session_state.gdelt_events]
if not records:
    st.info("Velg filtre og trykk «Hent hendelser». Første test kan gjerne være et smalt søk over 7–14 dager.")
    st.stop()

frame = pd.DataFrame(records)
frame["actors"] = frame["actors"].apply(lambda values: ", ".join(values))
visible_columns = [
    "event_date", "title", "category", "subcategory", "domain", "country",
    "location", "actors", "confidence", "market_sensitivity", "significance", "url",
]

m1, m2, m3, m4 = st.columns(4)
m1.metric("Hendelser", len(frame))
m2.metric("Land", int(frame["country"].replace("", pd.NA).nunique()))
m3.metric("Kategorier", int(frame["category"].replace("", pd.NA).nunique()))
m4.metric("Neste side", "Ja" if st.session_state.get("gdelt_next_cursor") else "Nei")

st.subheader("Strukturert input-strøm")
st.dataframe(
    frame[visible_columns],
    use_container_width=True,
    hide_index=True,
    column_config={"url": st.column_config.LinkColumn("Kilde")},
)

csv_data = frame.drop(columns=["raw"]).to_csv(index=False).encode("utf-8")
a, b = st.columns(2)
with a:
    st.download_button("Last ned CSV", data=csv_data, file_name="gdelt_events.csv", mime="text/csv", use_container_width=True)
with b:
    if st.button("Lagre i lokal database", use_container_width=True):
        changed = save_events(st.session_state.gdelt_events)
        st.success(f"Databasen ble oppdatert ({changed} innsettinger/oppdateringer).")

st.subheader("Neste analyseledd")
st.markdown(
    """
Denne siden stopper bevisst før en fri AI-konklusjon. Neste modul skal motta et begrenset utvalg hendelser og:

1. avgjøre hvilke poster som beskriver samme underliggende hendelse,
2. beskrive den kausale markedsbetydningen,
3. finne historiske analogier,
4. veie analogiene mot dagens særlige betingelser og et par ferske nyhetssøk,
5. skille statistisk grunnlag fra AI-ens helhetsvurdering og oppgi usikkerhet for begge.
"""
)
