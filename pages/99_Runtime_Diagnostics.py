from __future__ import annotations

import streamlit as st

from build_info import render_build_badge
from runtime_diagnostics import build_runtime_diagnostic_report


st.set_page_config(page_title="Runtime Diagnostics · PriceGauger", page_icon="🧭", layout="wide")
render_build_badge()
st.title("Runtime Diagnostics")
st.caption("Read-only kontroll av den persistente kjeden fra Telegram til Decision State.")

report = build_runtime_diagnostic_report()

col1, col2, col3 = st.columns(3)
col1.metric("Backend", report.backend)
col2.metric("Konfigurasjonskilde", report.source)
col3.metric("Runtime", report.runtime)
st.code(report.database_fingerprint, language=None)
st.caption("Fingeravtrykket inneholder ikke brukernavn, passord eller full database-URL.")

st.subheader("Persistente tabeller")
rows = [
    {
        "tabell": item.table,
        "status": item.status,
        "rader": item.count,
        "siste tidspunkt": item.latest,
        "feil": item.error,
    }
    for item in report.tables
]
st.dataframe(rows, use_container_width=True, hide_index=True)

st.subheader("Decision State-markeder")
if report.decision_markets:
    st.write(", ".join(report.decision_markets))
else:
    st.warning("Ingen Decision State-markeder ble funnet.")

st.subheader("Automatisk diagnose")
for message in report.diagnosis:
    if "complete" in message.lower():
        st.success(message)
    else:
        st.warning(message)

st.info(
    "Denne siden analyserer bare databasen som Streamlit faktisk er koblet til. "
    "Den skriver eller reparerer ingenting."
)
