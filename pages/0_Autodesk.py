from __future__ import annotations

import streamlit as st

from build_info import render_build_badge
from realtime_market_data import RealtimeMarketDataStore
from trading_desk_v2_context import load_trading_desk_contexts_v2


st.set_page_config(page_title="Autodesk · PriceGauger", page_icon="🧠", layout="wide")
render_build_badge()

st.markdown(
    """
    <style>
    div[data-testid="stMainBlockContainer"], .block-container {
        max-width: 100% !important;
        padding-left: 1.25rem !important;
        padding-right: 1.25rem !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

header_left, header_right = st.columns([5, 1])
with header_left:
    st.title("Autodesk")
    st.caption(
        "Parallell TradingDesk-lab for opportunity-first handel: observer markedet, "
        "oppdag interessante hendelser, vurder helheten og handle bare når edge er god nok."
    )
with header_right:
    st.page_link("pages/0_TradingDesk.py", label="TradingDesk", icon="📊")

# Autodesk deliberately consumes the same canonical data/workspace as TradingDesk.
# It must not grow a parallel market database just because the decision model differs.
store = RealtimeMarketDataStore()
try:
    contexts = load_trading_desk_contexts_v2()
except Exception as exc:
    st.warning(f"Autodesk kunne ikke lese det felles v2-workspacet: {exc}")
    st.stop()

markets = sorted(contexts)
if not markets:
    st.info("Venter på aktive v2-workspaces.")
    st.stop()

requested = str(st.query_params.get("market", "") or "").strip()
market = st.selectbox(
    "Marked",
    markets,
    index=markets.index(requested) if requested in markets else 0,
    key="autodesk-market-v1",
)
st.query_params["market"] = market
context = contexts[market]

st.markdown("### Opportunity pipeline")
pipeline = st.columns(5)
pipeline[0].markdown("**1 · Observe**\n\nFelles canonical markedsdata og markedstilstand.")
pipeline[1].markdown("**2 · Detect**\n\nBreakout, reclaim, kompresjon, momentumskifte og andre kandidater.")
pipeline[2].markdown("**3 · Judge**\n\nHelhetsmodell vurderer evidens, motargumenter og historiske analoger.")
pipeline[3].markdown("**4 · Risk**\n\nNO-TRADE, confidence, sizing og invalidasjon før kapital risikeres.")
pipeline[4].markdown("**5 · Learn**\n\nOutcome tilbake til felles memory for alle modeller.")

left, right = st.columns([2, 1], gap="large")
with left:
    st.markdown("### Markedsobservasjon")
    st.caption(
        "Denne første versjonen etablerer arbeidsplassen og datagrensen. Neste steg er å "
        "gjenbruke TradingDesk-chartet her og legge opportunity-detektorer oppå samme canonical feed."
    )
    identity = f"market_id {context.market_id}"
    if context.instrument is not None:
        identity += (
            f" · instrument_id {context.instrument.instrument_id}"
            f" · {context.instrument.provider}:{context.instrument.provider_instrument_id}"
        )
    st.code(identity, language=None)

    st.info(
        "Autodesk har foreløpig ingen execution-authority. Den utvikles som observasjon/shadow-lab "
        "før noen modell kan promoteres til live handel."
    )

with right:
    st.markdown("### Beslutningskontrakt")
    st.markdown(
        """
- **WAIT / NO-TRADE er et fullverdig resultat.**
- En indikator er evidens eller trigger, ikke automatisk ordre.
- Alle modeller leser samme rådata og deler læringshistorikk.
- En opportunity må ha eksplisitt confidence, invalidasjon og forventet risiko.
- Replay → shadow → mikro-live → normal størrelse før økt authority.
        """
    )

st.divider()
st.markdown("### Første utviklingsspor")
st.markdown(
    """
1. Flytt det canonical TradingDesk-chartet inn som delt komponent, uten å kopiere datalagring.
2. Lag første opportunity-detektor: **volumsone → breakout → acceptance/retest**.
3. Lag en felles `Opportunity`-hendelse som andre detektorer senere kan produsere.
4. La MACD Supervisor og den holistiske modellen være **vurderere** av kandidaten, ikke kontinuerlige tvangstradere.
5. Mål opportunity capture, adverse capture, MAE/MFE, drawdown og NO-TRADE-kvalitet i replay/shadow.
    """
)
