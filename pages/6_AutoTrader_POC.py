from __future__ import annotations

import streamlit as st

from autotrader_live_close_ui_v1 import render_live_close_v1
from autotrader_macd_dry_run_ui_v2 import render_macd_dry_run_monitor_v2
from autotrader_operating_mode_ui_v2 import render_operating_modes_v2
from autotrader_risk_control_ui_v2 import render_risk_control_monitor_v2
from build_info import render_build_badge
from trading_desk_product_panel import render_saxo_product_panel
from trading_desk_products import MARKET_SEARCH_TERMS


st.set_page_config(page_title="AutoTrader · PriceGauger", page_icon="⚙️", layout="wide")
render_build_badge()
st.title("AutoTrader")
st.caption(
    "Execution, posisjonshåndtering og risikokontroll. Produktbrowseren finner egnede instrumenter; AutoTrader skal "
    "konsumere bare eksplisitt autoriserte identiteter og operere innen harde kapital-/marginrammer."
)

st.warning(
    "LIVE close-only er fortsatt den eneste autonome execution-authority som er aktiv. Ingen automatisk OPEN/ADD er aktivert "
    "av operasjonsmodus-kontrakten under."
)

render_operating_modes_v2()

st.divider()
render_live_close_v1()

st.divider()
render_risk_control_monitor_v2()

st.divider()
render_macd_dry_run_monitor_v2()

st.divider()
st.subheader("Manuell execution-test")
st.caption(
    "Denne delen er fortsatt den eksisterende SIM-låste ordrebanen. Bruk Produktbrowser for discovery; "
    "her verifiseres selve execution-flyten."
)
markets = tuple(MARKET_SEARCH_TERMS.keys())
market = st.selectbox(
    "Marked",
    markets,
    index=0,
    help="Velg markedet for den eksisterende manuelle SIM execution-testen.",
)

render_saxo_product_panel(market)
