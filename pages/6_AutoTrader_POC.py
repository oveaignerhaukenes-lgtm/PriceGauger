from __future__ import annotations

import streamlit as st

from autotrader_breakeven_reset_ui_v1 import render_breakeven_reset_controls_v1
from autotrader_macd_dry_run_ui_v2 import render_macd_dry_run_monitor_v2
from autotrader_risk_control_ui_v2 import render_risk_control_monitor_v2
from autotrader_risk_control_v2 import _position_observations_v2
from autotrader_pnl_comparison_v2 import load_automanager_pnl_comparison_v2
from autotrader_strategy_enrollment_v2 import load_active_strategy_enrollments_v2
from autotrader_v3_fleet_read_model_v1 import build_fleet_read_model_v3
from autotrader_v3_fleet_ui_v1 import render_autotrader_v3_fleet_preview
from autotrader_v3_regime_chart_ui_v1 import render_v3_regime_return_chart
from build_info import render_build_badge
from trading_desk_v2_context import load_trading_desk_contexts_v2
from tradingdesk_automanage_panel_v2 import render_tradingdesk_automanage_panel_v2
from saxo_provider import configured_client
from autotrader_v3_macd_histogram_v1 import STRATEGY_KEY_V3
from autotrader_v3_sim_authority_v1 import sim_authority_armed_v3, set_sim_authority_v3
from autotrader_v3_live_authority_v1 import live_authority_armed_v3, set_live_authority_v3


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

v3_tab, main_tab, runtime_tab = st.tabs(("V3 Fleet", "AutoManage v2", "Runtime / signal"))

with v3_tab:
    st.subheader("ENGINE V3 · Target Inventory")
    st.caption("V3 Fleet · simulator eller LIVE. Alle kontroller i denne fanen tilhører ENGINE V3. LIVE authority = ON betyr at v3-workeren faktisk forvalter den eksakte Saxo-boundaryen.")
    st.info("V3 · MACD-Histogram 5m ligger nå i simulatoren: 0,01-trinn, target inventory og hard-reversal FLAT. SIM-authority nedenfor starter bare den automatiske simulator-driveren; den kan ikke åpne, lukke eller overta en Saxo-posisjon.")
    try:
        v3_enrollments = tuple(
            item
            for item in load_active_strategy_enrollments_v2()
            if int(item.market_id) == int(context.market_id)
        )
        client = configured_client()
        v3_observations = _position_observations_v2(client) if client is not None else ()
        fleet_rows = build_fleet_read_model_v3(v3_enrollments, v3_observations)
        render_autotrader_v3_fleet_preview(fleet_rows)
        trailing = tuple(item for item in v3_enrollments if item.strategy_key == STRATEGY_KEY_V3)
        if trailing:
            st.markdown("**V3 simulator authority**")
            for item in trailing:
                armed = sim_authority_armed_v3(item.pilot_key)
                desired = st.toggle(
                    f"ENGINE V3 · {item.market_name} · SIM",
                    value=armed,
                    key=f"v3-sim-arm:{item.pilot_key}",
                    help="Kjører beslutningsmotoren på lukkede 5m-bars. Ingen Saxo POST.",
                )
                if desired != armed:
                    set_sim_authority_v3(item.pilot_key, desired)
                    st.rerun()

                live_armed = live_authority_armed_v3(item.pilot_key)
                live_desired = st.toggle(
                    f"ENGINE V3 · {item.market_name} · LIVE",
                    value=live_armed,
                    key=f"v3-live-arm:{item.pilot_key}",
                    disabled=desired,
                    help="ON = denne v3 AutoTraderen er aktiv i LIVE og workeren forvalter den eksakte Saxo account + UIC + AssetType-boundaryen.",
                )
                if live_desired != live_armed:
                    set_live_authority_v3(item.pilot_key, live_desired)
                    st.rerun()
                if live_armed:
                    st.success("LIVE AKTIV · worker execution er koblet. Eksisterende Saxo-inventory inngår i v3 reconciliation.")

        live_groups: dict[tuple[str, int, str, int], list] = {}
        for enrollment in v3_enrollments:
            key = (
                enrollment.account_id, int(enrollment.uic), enrollment.asset_type,
                int(enrollment.instrument_id),
            )
            live_groups.setdefault(key, []).append(enrollment)
        for key, group in live_groups.items():
            try:
                comparison = load_automanager_pnl_comparison_v2(tuple(group))
            except Exception as exc:
                st.caption(f"UIC {key[1]} · v3-regimegraf venter: {exc}")
                continue
            render_v3_regime_return_chart(comparison)
    except Exception as exc:
        st.warning(f"V3-preview kunne ikke bygges: {exc}")

with main_tab:
    st.subheader("ENGINE V2 · AutoManage")
    st.caption("Alle kontroller i denne fanen tilhører ENGINE V2. V2 og V3 har separat authority og runtime.")
    render_tradingdesk_automanage_panel_v2(context)

with runtime_tab:
    render_breakeven_reset_controls_v1()
    st.divider()
    st.subheader("RiskControl")
    render_risk_control_monitor_v2()
    st.divider()
    st.subheader("30m MACD runtime")
    render_macd_dry_run_monitor_v2()