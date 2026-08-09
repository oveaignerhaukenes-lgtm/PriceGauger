from __future__ import annotations

import streamlit as st

from navigation_config import build_navigation


st.set_page_config(page_title="PriceGauger", page_icon="📡", layout="wide")

page = st.navigation(build_navigation(st), position="sidebar", expanded=True)

requested_market = st.query_params.get("open_market")
if isinstance(requested_market, list):
    requested_market = requested_market[0] if requested_market else None
if requested_market:
    st.switch_page(
        "pages/7_Forecast_Learning.py",
        query_params={"market": str(requested_market)},
    )

page.run()
