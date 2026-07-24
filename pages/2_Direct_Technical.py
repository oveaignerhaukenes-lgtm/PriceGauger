from __future__ import annotations

import pandas as pd
import streamlit as st

from build_info import render_build_badge
from config import twelve_data_api_key
from market_data import MarketRequest, TwelveDataProvider, YahooProvider, fetch_market_data
from saxo_provider import SaxoPriceProvider
from technical_analysis import TechnicalSnapshot, build_multi_timeframe_snapshot
from technical_regime import TechnicalRegime, build_technical_regime


st.set_page_config(page_title="Direct – Technical", page_icon="📈", layout="wide")
render_build_badge()

st.markdown(
    """
    <style>
    [data-testid="stMetric"] {
        min-width: 0;
    }
    [data-testid="stMetricLabel"] {
        font-size: 0.78rem;
        line-height: 1.15;
        white-space: normal;
        overflow: visible;
        text-overflow: clip;
    }
    [data-testid="stMetricValue"] {
        font-size: clamp(1.25rem, 2.1vw, 2rem);
        line-height: 1.08;
        white-space: normal;
        overflow-wrap: anywhere;
        word-break: normal;
        overflow: visible;
        text-overflow: clip;
    }
    [data-testid="stMetricValue"] > div {
        white-space: normal;
        overflow-wrap: anywhere;
        overflow: visible;
        text-overflow: clip;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

ASSETS = {
    "Brent": {"yahoo": "BZ=F"},
    "Silver": {"twelve": "XAG/USD", "yahoo": "SI=F"},
    "Gold": {"twelve": "XAU/USD", "yahoo": "GC=F"},
    "DXY": {"yahoo": "DX-Y.NYB"},
}
TIMEFRAMES = {
    "5m": "5min",
    "30m": "30min",
    "1h": "1h",
}


def providers() -> list:
    configured = [SaxoPriceProvider()]
    api_key = twelve_data_api_key()
    if api_key:
        configured.append(TwelveDataProvider(api_key))
    configured.append(YahooProvider())
    return configured


def fetch_frames(asset: str, outputsize: int) -> tuple[dict[str, pd.DataFrame], dict[str, str]]:
    frames: dict[str, pd.DataFrame] = {}
    sources: dict[str, str] = {}
    configured = providers()
    for timeframe, interval in TIMEFRAMES.items():
        request = MarketRequest(
            asset_name=asset,
            interval=interval,
            outputsize=outputsize,
            symbols=ASSETS[asset],
        )
        result = fetch_market_data(request, configured)
        frames[timeframe] = result.frame
        sources[timeframe] = result.provider_name
    return frames, sources


def render_snapshot(snapshot: TechnicalSnapshot) -> None:
    with st.container(border=True):
        st.markdown(f"### {snapshot.timeframe}")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Pris", f"{snapshot.price:,.3f}")
        c2.metric("RSI 14", f"{snapshot.rsi_14:.1f}" if snapshot.rsi_14 is not None else "—")
        c3.metric(
            "MACD histogram",
            f"{snapshot.macd_histogram:+.4f}" if snapshot.macd_histogram is not None else "—",
        )
        c4.metric("ATR 14", f"{snapshot.atr_14_pct:.2f} %" if snapshot.atr_14_pct is not None else "—")
        for reading in snapshot.readings:
            st.write(f"• {reading.display}")


def render_regime(regime: TechnicalRegime) -> None:
    with st.container(border=True):
        st.markdown("### Direct – Technical")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Technical bias", regime.bias)
        c2.metric("Signal quality", regime.signal_quality)
        c3.metric("Reversal risk", regime.reversal_risk)
        c4.metric("Recommended monitoring", regime.review_label)
        st.write(f"**Regime:** {regime.regime}")
        for reason in regime.rationale:
            st.write(f"• {reason}")


st.title("Direct – Technical")
st.caption(
    "Deterministisk flertidsrammeanalyse fra OHLCV. Oppdateringsintervallet er en "
    "overvåkingsanbefaling, ikke en prognose for når markedet snur."
)

with st.sidebar:
    st.header("Teknisk analyse")
    asset = st.selectbox("Marked", list(ASSETS))
    outputsize = st.selectbox("Prisbarer per tidsramme", [150, 300, 600, 1200], index=1)
    run_analysis = st.button("Oppdater teknisk analyse", type="primary", use_container_width=True)

state_key = f"direct_technical_{asset}_{outputsize}"
if run_analysis:
    try:
        with st.spinner("Henter markedsdata og beregner indikatorer …"):
            frames, sources = fetch_frames(asset, outputsize)
            snapshots = build_multi_timeframe_snapshot(frames, asset=asset)
            regime = build_technical_regime(snapshots)
            st.session_state[state_key] = {
                "snapshots": snapshots,
                "regime": regime,
                "sources": sources,
            }
    except Exception as exc:
        st.error(f"Kunne ikke bygge teknisk analyse: {exc}")

result = st.session_state.get(state_key)
if result is None:
    st.info("Trykk «Oppdater teknisk analyse» for å hente 5m, 30m og 1h og beregne Direct – Technical.")
else:
    snapshots: dict[str, TechnicalSnapshot] = result["snapshots"]
    regime: TechnicalRegime = result["regime"]
    sources: dict[str, str] = result["sources"]

    render_regime(regime)
    st.caption(" · ".join(f"{timeframe}: {sources.get(timeframe, 'ukjent')}" for timeframe in TIMEFRAMES))

    st.markdown("### Indikatorgrunnlag")
    columns = st.columns(3)
    for column, timeframe in zip(columns, TIMEFRAMES):
        with column:
            snapshot = snapshots.get(timeframe)
            if snapshot is None:
                st.warning(f"Ingen gyldig analyse for {timeframe}.")
            else:
                render_snapshot(snapshot)
