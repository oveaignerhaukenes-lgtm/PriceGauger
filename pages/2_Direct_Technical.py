from __future__ import annotations

import html

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
    .pg-metric-grid {
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 1rem;
        margin: .35rem 0 1rem 0;
    }
    .pg-metric {
        min-width: 0;
    }
    .pg-metric-label {
        font-size: .74rem;
        line-height: 1.2;
        color: rgba(49, 51, 63, .78);
        margin-bottom: .35rem;
        white-space: normal;
    }
    .pg-metric-value {
        font-size: 1.18rem;
        line-height: 1.2;
        font-weight: 400;
        white-space: normal;
        overflow: visible;
        overflow-wrap: break-word;
        word-break: normal;
        text-overflow: clip;
    }
    .pg-snapshot-grid .pg-metric-value {
        font-size: 1rem;
    }
    @media (max-width: 900px) {
        .pg-metric-grid {
            grid-template-columns: repeat(2, minmax(0, 1fr));
        }
    }
    @media (max-width: 560px) {
        .pg-metric-grid {
            grid-template-columns: 1fr;
        }
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


def render_metric_grid(items: list[tuple[str, str]], *, snapshot: bool = False) -> None:
    cards = "".join(
        (
            '<div class="pg-metric">'
            f'<div class="pg-metric-label">{html.escape(label)}</div>'
            f'<div class="pg-metric-value">{html.escape(value)}</div>'
            "</div>"
        )
        for label, value in items
    )
    extra_class = " pg-snapshot-grid" if snapshot else ""
    st.markdown(
        f'<div class="pg-metric-grid{extra_class}">{cards}</div>',
        unsafe_allow_html=True,
    )


def render_snapshot(snapshot: TechnicalSnapshot) -> None:
    with st.container(border=True):
        st.markdown(f"### {snapshot.timeframe}")
        render_metric_grid(
            [
                ("Pris", f"{snapshot.price:,.3f}"),
                ("RSI 14", f"{snapshot.rsi_14:.1f}" if snapshot.rsi_14 is not None else "—"),
                (
                    "MACD histogram",
                    f"{snapshot.macd_histogram:+.4f}" if snapshot.macd_histogram is not None else "—",
                ),
                ("ATR 14", f"{snapshot.atr_14_pct:.2f} %" if snapshot.atr_14_pct is not None else "—"),
            ],
            snapshot=True,
        )
        for reading in snapshot.readings:
            st.write(f"• {reading.display}")


def render_regime(regime: TechnicalRegime) -> None:
    with st.container(border=True):
        st.markdown("### Direct – Technical")
        render_metric_grid(
            [
                ("Technical bias", regime.bias),
                ("Signal quality", regime.signal_quality),
                ("Reversal risk", regime.reversal_risk),
                ("Recommended monitoring", regime.review_label),
            ]
        )
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
