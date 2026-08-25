from __future__ import annotations

import streamlit as st

from autotrader_live_close_ui_v1 import render_live_close_v1
from autotrader_macd_dry_run_ui_v2 import render_macd_dry_run_monitor_v2
from autotrader_product_explorer_ui import render_saxo_product_explorer
from autotrader_product_scanner_ui_v2 import render_product_scanner_v2
from autotrader_risk_control_ui_v2 import render_risk_control_monitor_v2
from build_info import render_build_badge
from trading_desk_product_panel import render_saxo_product_panel
from trading_desk_products import MARKET_SEARCH_TERMS


st.set_page_config(page_title="AutoTrader · PriceGauger", page_icon="⚙️", layout="wide")
render_build_badge()
st.title("AutoTrader")
st.caption(
    "Risk-control observerer åpne Saxo LIVE-posisjoner og produserer WOULD_CLOSE når tersklene treffes. "
    "Close-only PoC kan, når begge sikkerhetsnøkler er aktivert, sende en automatisk motordre som kun "
    "skal redusere/lukke den allerede triggete posisjonen."
)

st.warning(
    "LIVE close-only er fysisk avgrenset fra entry-logikken: ingen automatisk kjøps-/entry-strategi er aktiv. "
    "MACD-laget er fortsatt kun dry-run."
)

render_live_close_v1()

st.divider()
render_risk_control_monitor_v2()

st.divider()
render_macd_dry_run_monitor_v2()

st.divider()
render_product_scanner_v2()

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
