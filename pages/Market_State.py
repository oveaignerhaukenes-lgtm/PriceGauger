from __future__ import annotations

import streamlit as st

from market_state_ui import render_market_state_panel
from telegram_query_builder import fetch_latest_search_plan

st.set_page_config(page_title="Market State · PriceGauger", page_icon="🧭", layout="wide")
st.title("Market State")
st.caption("Testbar rolling-state motor for firetimers markedsanbefalinger.")

try:
    plan = fetch_latest_search_plan()
except Exception as exc:
    st.error(f"Telegram-strømmen kunne ikke leses: {exc}")
    st.stop()

if plan is None:
    st.info("Venter på en relevant Telegram-melding.")
    st.stop()

with st.container(border=True):
    st.markdown("**Aktiv Telegram-observasjon**")
    st.write(plan.message_text)
    st.caption(f"{plan.event_type} · {plan.target} · {plan.country or 'ukjent land'}")
    st.link_button("Åpne originalmelding", plan.message_url)

render_market_state_panel(plan)
