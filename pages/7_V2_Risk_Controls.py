from __future__ import annotations

import streamlit as st

from autotrader_pilot_equity_v2 import load_pilot_equity_v2
from autotrader_strategy_enrollment_v2 import EXECUTION_MODE_LIVE, load_active_strategy_enrollments_v2
from saxo_provider import LIVE_BASE_URL, configured_client
from tradingdesk_v2_margin_controls_v1 import render_v2_margin_controls_v1


st.set_page_config(page_title="V2 Risk Controls", layout="wide")
st.title("AutoTrader V2 · Risk Controls")
st.caption("Juster Margin Envelope for den aktive V2-piloten. Saxo-precheck forblir siste autoritet før OPEN/ADD.")

live = [item for item in load_active_strategy_enrollments_v2() if item.execution_mode == EXECUTION_MODE_LIVE and item.enabled]
if not live:
    st.info("Ingen aktiv V2 LIVE-pilot.")
    st.stop()

labels = {f"{item.market_name} · {item.strategy_key} · {item.account_id}": item for item in live}
selected = st.selectbox("V2-pilot", tuple(labels))
enrollment = labels[selected]

client = configured_client(base_url=LIVE_BASE_URL)
payload = client._get("port/v1/accounts/me")
rows = payload.get("Data") or []
account = next((row for row in rows if str(row.get("AccountId") or "") == str(enrollment.account_id)), None)
if account is None:
    st.error("Fant ikke pilotens Saxo-konto.")
    st.stop()

currency = str(account.get("Currency") or "").strip().upper()
equity = load_pilot_equity_v2(pilot_key=enrollment.pilot_key)
st.write(f"Pilotkapital: **{equity.allocated_capital:.2f} {currency}**")
render_v2_margin_controls_v1(
    pilot_key=enrollment.pilot_key,
    currency=currency,
    allocated_capital=float(equity.allocated_capital),
)
