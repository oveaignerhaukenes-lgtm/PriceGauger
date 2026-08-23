from __future__ import annotations

import streamlit as st

from autotrader_macd_dry_run_ui_v2 import render_macd_dry_run_monitor_v2
from autotrader_product_explorer_ui import render_saxo_product_explorer
from autotrader_risk_dry_run_ui_v2 import render_risk_dry_run_monitor_v2
from build_info import render_build_badge
from trading_desk_product_panel import render_saxo_product_panel
from trading_desk_products import MARKET_SEARCH_TERMS


st.set_page_config(page_title="AutoTrader · PriceGauger", page_icon="⚙️", layout="wide")
render_build_badge()
st.title("AutoTrader")
st.caption(
    "Risk-control leser åpne Saxo-posisjoner i read-only dry-run. Manuell ordreutførelse er fortsatt "
    "hardlåst til den eksisterende SIM-sikkerhetsveien; LIVE-appen får ikke ordre fra denne siden."
)

st.warning(
    "Ingen automatisk ordreutførelse er aktiv. Risk-control produserer bare WOULD_CLOSE, "
    "og MACD-laget produserer bare observerbare dry-run-signaler."
)

render_risk_dry_run_monitor_v2()

st.divider()
render_macd_dry_run_monitor_v2()

st.divider()
markets = tuple(MARKET_SEARCH_TERMS.keys())
market = st.selectbox(
    "Marked",
    markets,
    index=0,
    help="Velg markedet du vil finne LONG/SHORT Mini/KO-produkter for.",
)

render_saxo_product_panel(market)

st.divider()
render_saxo_product_explorer()
