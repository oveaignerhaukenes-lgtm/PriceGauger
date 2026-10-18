"""Separate, read-only cycle research page; independent of Markedsrytme PR #726.

Shows a causal wavelet-inspired rhythm map, a simple lag-correlation
cross-check, and independently confirmed directional-change turns.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from canonical_market_bars_v2 import CanonicalMarketBarStoreV2
from instrument_registry_v2 import list_subscribed_sources_v2
from market_rhythm_wavelet_research_v1 import (
    PERIODS_MIN, build_cycle_research_v1,
)

st.set_page_config(page_title="Sykluslaboratorium · PriceGauger", page_icon="〰️", layout="wide")
st.title("Sykluslaboratorium")
st.caption(
    "Forskningspanel – ikke en handelsstrategi. Vi undersøker om markedet "
    "gjentar svingninger med bestemte tidsintervaller. Ingen ordre, ingen "
    "automatiske strategivalg og ingen ekstra datainnsamling."
)

try:
    candidates = tuple(sorted(
        list_subscribed_sources_v2(provider="saxo"),
        key=lambda source: (source.market_name, source.instrument_id),
    ))
except Exception as exc:
    st.error(f"Kan ikke lese instrumentlisten ({type(exc).__name__}).")
    st.stop()

if not candidates:
    st.info("Ingen registrerte, aktive Saxo-instrumenter med kanoniske markedsdata.")
    st.stop()


def _source_label(source):
    return f"{source.market_name} · {source.display_name} · UIC {source.provider_instrument_id}"


default_index = next(
    (i for i, item in enumerate(candidates) if "tech 100" in item.market_name.lower()), 0,
)
left, right = st.columns([3, 1])
with left:
    instrument = st.selectbox(
        "Instrument", candidates, index=default_index, format_func=_source_label,
        key="rhythm-research-instrument",
    )
with right:
    hours = st.selectbox(
        "Datavindu", (6, 24, 48, 168), index=1,
        format_func=lambda h: f"{h} timer" if h<168 else "7 døgn",
        key="rhythm-research-window",
    )


@st.cache_data(ttl=45, max_entries=12, show_spinner=False)
def _load_completed_closes(instrument_id: int, hours: int) -> pd.Series:
    now = datetime.now(timezone.utc)
    candles = CanonicalMarketBarStoreV2().load_instrument_range(
        instrument_id=int(instrument_id),
        start=now-timedelta(hours=hours),
        end=now,
        limit=12000,
    )
    valid=[]
    for candle in candles:
        start=pd.Timestamp(candle.bar_time)
        if start.tzinfo is None:
            start=start.tz_localize("UTC")
        closed_at=start.tz_convert("UTC")+pd.Timedelta(minutes=1)
        # Do not expose the forming candle as if its final close is known.
        if closed_at + pd.Timedelta(seconds=10) <= pd.Timestamp(now):
            valid.append((closed_at,float(candle.close)))
    if not valid:
        return pd.Series(dtype=float,index=pd.DatetimeIndex([],tz="UTC"))
    return pd.Series(
        [point[1] for point in valid],
        index=pd.DatetimeIndex([point[0] for point in valid]),
        dtype=float,
    )


def _scalogram_chart(research):
    matrix=research.normalized_power.tail(600).iloc[::3]
    fig=go.Figure(data=go.Heatmap(
        z=matrix.to_numpy().T,
        x=matrix.index,
        y=list(matrix.columns),
        colorscale="Viridis",
        colorbar=dict(title="Styrke (bp)"),
        hovertemplate="Tid %{x}<br>Periode %{y} min<br>Relativ styrke %{z:.2f} bp<extra></extra>",
    ))
    fig.update_layout(
        title="Hvilke rytmer er aktive? (ensidig wavelet-inspirert analyse)",
        xaxis_title="Ferdiglukket markedsminutt (UTC)",
        yaxis_title="Sykluslengde (minutter)",
        height=420,
        margin=dict(t=65,b=35,l=20,r=15),
        uirevision="research-wavelet-v1",
    )
    return fig


def _turn_chart(research):
    closes=research.prices.tail(500)
    fig=go.Figure()
    fig.add_trace(go.Scatter(
        x=closes.index,y=closes.to_numpy(),
        mode="lines",name="Ferdige 1m-kurser",
        line=dict(color="#94a3b8",width=1.5),
    ))
    turns=[x for x in research.confirmed_turns
           if x.pivot_at >= closes.index[0]][-45:]
    for kind, color, symbol in (
        ("PEAK","#ef4444","triangle-down"),
        ("TROUGH","#10b981","triangle-up"),
    ):
        matching=[x for x in turns if x.kind==kind]
        if not matching:
            continue
        fig.add_trace(go.Scatter(
            x=[x.pivot_at for x in matching],
            y=[x.price for x in matching],
            name="TOPP" if kind=="PEAK" else "BUNN",
            mode="markers",
            marker=dict(color=color,size=9,symbol=symbol),
            customdata=[x.confirmed_at.strftime("%d.%m %H:%M UTC") for x in matching],
            hovertemplate="Historisk pivot: %{x}<br>Pris: %{y:.2f}<br>Først kjent: %{customdata}<extra></extra>",
        ))
    fig.update_layout(
        title="Faktiske bekreftede vendinger (minst 0,10 %)",
        xaxis_title="Tid (UTC)", yaxis_title="Underliggende pris",
        height=330,margin=dict(t=55,b=35,l=20,r=15),
        legend=dict(orientation="h",y=-0.28),
        uirevision="research-turns-v1",
    )
    return fig


@st.fragment(run_every="60s")
def _render_research() -> None:
    try:
        closes=_load_completed_closes(int(instrument.instrument_id),hours)
        research=build_cycle_research_v1(closes)
    except Exception as exc:
        st.warning(f"Syklusdata utilgjengelige ({type(exc).__name__}). Ingen handelsfunksjoner påvirkes.")
        return

    if research.prices.empty:
        st.info("Ingen ferdiglukket markedsdata i valgt vindu.")
        return

    last=research.prices.index[-1]
    age_minutes=max(0,(datetime.now(timezone.utc)-last.to_pydatetime()).total_seconds()/60)
    st.caption(
        f"Kilde: {instrument.provider}:{instrument.provider_instrument_id} · "
        f"Siste fullførte candle: {last:%d.%m.%Y %H:%M UTC} · "
        f"{research.contiguous_bars} sammenhengende av {research.total_input_bars} 1m-lys"
    )
    if age_minutes>3:
        st.warning(
            f"Siste lys er {age_minutes:.0f} minutter gammelt. Markedet kan være "
            "stengt eller feed forsinket. Dette er ikke en LIVE-signalkilde."
        )
    if research.cut_at_gap:
        st.info(
            "Prisfeed inneholder tidsavbrudd. Analysen bruker bare siste "
            "sammenhengende handelsøkt, ikke syntetiske intervaller over pausen."
        )
    cols=st.columns(4)
    cols[0].metric("Tydeligste rytme",(
        f"{research.dominant_wavelet_minutes} min"
        if research.dominant_wavelet_minutes is not None else "ukjent"))
    cols[1].metric("Uavhengig periodetest",(
        f"{research.lag_correlation_minutes} min"
        if research.lag_correlation_minutes is not None else "ukjent"))
    cols[2].metric("Wavelet-kontrast",(
        f"{research.wavelet_contrast:.2f}×"
        if research.wavelet_contrast is not None else "ukjent"))
    cols[3].metric("Bekreftede vendinger",str(len(research.confirmed_turns)))
    st.caption(
        "Wavelet = hvilke svingperioder som har relativt tydelig gjentakelse. "
        "Periodetest = korrelasjon mellom prisendringer og dem for 4–64 minutter siden. "
        "Begge kan vise tilfeldige mønstre. Enighet betyr ikke forutsigbarhet."
    )
    st.plotly_chart(_scalogram_chart(research),use_container_width=True,config={"displaylogo":False})
    st.plotly_chart(_turn_chart(research),use_container_width=True,config={"displaylogo":False})
    with st.expander("Hva betyr dette – uten matematikken?",expanded=True):
        st.markdown(
            "- **Lyse felt** i varmekartet: relativt sterk bevegelse ved den angitte "
            "sykluslengden. Feltene er *målinger*, ikke fremtidige topp- eller bunntider.\n"
            "- **Tydeligste rytme**: den sterkeste undersøkte perioden nå, "
            "bare hvis den skiller seg tilstrekkelig ut; ellers ukjent.\n"
            "- **Periodetest**: en uavhengig, enkel sjekk om prisendringer "
            "ligner dem et bestemt antall minutter tidligere. Den er inspirert av "
            "syklusforskning, men er **ikke** John Ehlers' eksakte MESA/HT_DCPERIOD.\n"
            "- **Trekantene**: reelle vendepunkter markert på det historiske "
            "topp-/bunntidspunktet; hover viser når de først ble bekreftet.\n"
            "- **Praktisk bruk:** se om de samme rytmene kommer igjen, "
            "og om de to uavhengige målingene peker mot samme periode."
        )
    st.caption(
        "Metode: kausal ensidig Morlet-lignende filterbank på logaritmiske "
        "1m-avkastninger, tre syklusers oppvarming, og separat korrelasjon av "
        "tidligere avkastning. Minste undersøkte periode er 4 min; 1–2m kan "
        "ikke undersøkes pålitelig med en 1m-sluttkursfeed. "
        "Ingen automatisk regimeklassifisering, AI-valg eller ordre."
    )


_render_research()
