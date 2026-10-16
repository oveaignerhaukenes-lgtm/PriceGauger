from __future__ import annotations

import streamlit as st
from autotrader_v3_fleet_ui_v1 import render_v3_fleet_management_v1

st.set_page_config(page_title="AutoTrader V3 · PriceGauger",page_icon="🤖",layout="wide")
st.title("AutoTrader V3 · Fleet")
st.caption(
    "Oversikt, sammenligning og administrasjon av alle V3-instanser. "
    "Kontrollert reset/avstemming finnes nå under Administrer instansen på "
    "hver trader; gamle uverifiserte pending-låser kan aldri tvangsfrigjøres."
)
render_v3_fleet_management_v1()

st.info(
    "Strategi, periode, options/modifiers og eksponering kan endres både her "
    "og i TradingDesk. Endringen gjelder alltid den samme V3-instansen."
)
