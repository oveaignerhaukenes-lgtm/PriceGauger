from __future__ import annotations

import streamlit as st
from autotrader_v3_fleet_ui_v1 import render_v3_fleet_management_v1
from autotrader_v3_multi_account_ui_v1 import render_v3_instance_selector_v1
from autotrader_v3_order_guard_v1 import pending_order as pending_order_v3, mark as mark_order_v3
from autotrader_v3_live_authority_v1 import set_live_authority_v3

st.set_page_config(page_title="AutoTrader V3 · PriceGauger",page_icon="🤖",layout="wide")
st.title("AutoTrader V3 · Fleet")
st.caption("Oversikt, sammenligning og administrasjon av alle V3-instanser. For rask tuning av én autotrader brukes TradingDesk.")
render_v3_fleet_management_v1()

st.divider()
with st.expander("Kontoer og recovery",expanded=False):
    selected_instance=render_v3_instance_selector_v1(key_prefix="v3-fleet-account")
    if selected_instance is not None:
        trader_id=selected_instance.instance_id
        pending=pending_order_v3(account_id=selected_instance.account_id,uic=selected_instance.uic,asset_type=selected_instance.asset_type)
        if pending is not None:
            st.warning("En uavklart tidligere LIVE-ordre holder denne Saxo-boundaryen låst. Kontroller Saxo-posisjonen før recovery.")
            if st.button("Frigi gammel pending-lock og slå LIVE av",key=f"v3-release-pending:{trader_id}"):
                set_live_authority_v3(trader_id, False)
                mark_order_v3(request_key=pending["request_key"],state="REJECTED",detail="Operator released stale pending lock; LIVE authority disarmed before release")
                st.success("Pending-lock er frigitt og LIVE er slått AV.")
                st.rerun()

st.info("Strategi, periode, options/modifiers og eksponering kan endres både her og i TradingDesk. Endringen gjelder alltid den samme V3-instansen.")
