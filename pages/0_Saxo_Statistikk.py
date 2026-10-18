from __future__ import annotations

import streamlit as st

from autotrader_v3_saxo_history_ui_v1 import render_v3_saxo_statistics_v1

st.set_page_config(page_title="Saxo-statistikk · PriceGauger", page_icon="📈", layout="wide")
st.title("Saxo · faktisk kontohistorikk")
st.caption(
    "Automatisk innsamlet og lagret fra Saxo OpenAPI. "
    "Ingen utfylling eller manuell eksport. SIM-statistikk holdes adskilt."
)
render_v3_saxo_statistics_v1()
