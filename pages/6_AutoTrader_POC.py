from __future__ import annotations

import streamlit as st

from autotrader_macd_dry_run_ui_v2 import render_macd_dry_run_monitor_v2
from autotrader_risk_control_ui_v2 import render_risk_control_monitor_v2
from build_info import render_build_badge
from trading_desk_v2_context import load_trading_desk_contexts_v2
from tradingdesk_automanage_panel_v2 import render_tradingdesk_automanage_panel_v2


ACTIVE_MARKET_KEY = "autotrader-v2-market"
TRADINGDESK_MARKET_KEY = "tradingdesk-v2-market"


st.set_page_config(page_title="AutoTrader · PriceGauger", page_icon="⚙️", layout="wide")
render_build_badge()
st.title("AutoTrader")
st.caption(
    "Canonical LIVE AutoManage workspace. Strategien leser ferdig lukkede 30m-bars; execution går gjennom "
    "separate CLOSE/OPEN safety-gates og bindes til eksakt Saxo account + UIC + AssetType."
)

try:
    contexts = load_trading_desk_contexts_v2()
except Exception as exc:
    st.error(f"AutoTrader kunne ikke lese canonical v2 workspaces: {exc}")
    st.stop()

available_markets = tuple(sorted(contexts))
if not available_markets:
    st.info("Venter på aktive canonical v2 workspaces.")
    st.stop()

preferred_market = st.session_state.get(ACTIVE_MARKET_KEY)
if preferred_market not in available_markets:
    preferred_market = st.session_state.get(TRADINGDESK_MARKET_KEY)
if preferred_market not in available_markets:
    preferred_market = available_markets[0]
st.session_state[ACTIVE_MARKET_KEY] = preferred_market

header_left, header_right = st.columns([3, 1], gap="large")
with header_left:
    market = st.selectbox(
        "Marked",
        available_markets,
        index=available_markets.index(preferred_market),
        key=ACTIVE_MARKET_KEY,
        help="Valget beholdes gjennom Streamlit-reruns og brukes som canonical marked for AutoManage-panelet.",
    )
with header_right:
    st.page_link("pages/0_TradingDesk.py", label="Åpne TradingDesk", icon="📊")

# Keep the shared TradingDesk selection aligned while navigating between the two
# operational surfaces. The value is only a UI preference; execution identity is
# always re-resolved from the canonical context and Saxo product identity.
st.session_state[TRADINGDESK_MARKET_KEY] = market
context = contexts[market]

st.info(
    "Testmodus long/flat + Full auto betyr: LONG → EXIT/FLAT på bearish MACD-kryss → "
    "RE-ENTRY LONG på neste bullish MACD-kryss. Velg flip som shadow for å sammenligne mot "
    "LONG → SHORT → LONG på de samme lukkede 30m-barene."
)

main_tab, runtime_tab = st.tabs(("AutoManage", "Runtime / signal"))
with main_tab:
    render_tradingdesk_automanage_panel_v2(context)

with runtime_tab:
    st.subheader("RiskControl")
    render_risk_control_monitor_v2()
    st.divider()
    st.subheader("30m MACD runtime")
    render_macd_dry_run_monitor_v2()
