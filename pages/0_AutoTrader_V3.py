from __future__ import annotations

import streamlit as st
from autotrader_v3_fleet_ui_v1 import render_v3_fleet_management_v1
from autotrader_v3_multi_account_ui_v1 import render_v3_instance_selector_v1

st.set_page_config(page_title='AutoTrader V3 · PriceGauger',page_icon='🤖',layout='wide')
st.title('AutoTrader V3 · Fleet')
st.caption('Oversikt, sammenligning og administrasjon av alle V3-instanser. For rask tuning av én autotrader brukes TradingDesk.')

# Fleet is the primary surface. It deliberately reads the same instance-owned config
# that TradingDesk edits; there is no page-local strategy or modifier state.
render_v3_fleet_management_v1()

st.divider()
with st.expander('Legg til / velg konto',expanded=False):
    render_v3_instance_selector_v1(key_prefix='v3-fleet-account')

st.info('Strategi, periode, options/modifiers og eksponering kan endres både her og i TradingDesk. Endringen gjelder alltid den samme V3-instansen.')
