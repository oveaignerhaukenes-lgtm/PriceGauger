from __future__ import annotations

import streamlit as st

from autotrader_macd_dry_run_ui_v2 import render_macd_dry_run_monitor_v2
from autotrader_product_explorer_ui import render_saxo_product_explorer
from build_info import render_build_badge
from trading_desk_product_panel import render_saxo_product_panel
from trading_desk_products import MARKET_SEARCH_TERMS


st.set_page_config(page_title="AutoTrader · PriceGauger", page_icon="⚙️", layout="wide")
render_build_badge()
st.title("AutoTrader")
st.caption(
    "Manuell Saxo SIM-handel gjennom samme produktvalg, sizing, pre-check, bekreftelse og read-back "
    "som brukes i TradingDesk. Første automatiseringslag kjører kun som observerbar MACD dry-run."
)

st.warning(
    "AutoTrader er fortsatt hardlåst til Saxo SIM. MACD dry-run sender ingen ordre, og den manuelle "
    "ordreveien krever fortsatt Saxo pre-check og eksplisitt bekreftelse."
)

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
