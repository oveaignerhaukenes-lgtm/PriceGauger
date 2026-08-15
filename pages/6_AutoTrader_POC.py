from __future__ import annotations

import streamlit as st

from autotrader_product_explorer_ui import render_saxo_product_explorer
from build_info import render_build_badge
from trading_desk_product_panel import render_saxo_product_panel
from trading_desk_products import MARKET_SEARCH_TERMS


st.set_page_config(page_title="AutoTrader · PriceGauger", page_icon="⚙️", layout="wide")
render_build_badge()
st.title("AutoTrader")
st.caption(
    "Manuell Saxo SIM-handel gjennom samme produktvalg, sizing, pre-check, bekreftelse og read-back "
    "som brukes i TradingDesk. Ingen automatisk strategi/entry er koblet inn."
)

st.warning(
    "AutoTrader er fortsatt hardlåst til Saxo SIM. LIVE-ordering er blokkert i execution-laget, "
    "og ordre sendes bare etter Saxo pre-check og eksplisitt manuell bekreftelse."
)

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
