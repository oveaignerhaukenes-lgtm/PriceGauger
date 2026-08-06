from __future__ import annotations

import streamlit as st

from navigation_config import build_navigation


st.set_page_config(page_title="PriceGauger", page_icon="📡", layout="wide")

page = st.navigation(build_navigation(st), position="sidebar", expanded=True)
page.run()
