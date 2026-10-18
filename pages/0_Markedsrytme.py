"""Markedsrytme: live-refreshing READ-ONLY market structure observatory.

Only canonical 1m completed data. No Saxo client, strategy configuration,
persistent research writes, or execution authority.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from autotrader_market_rhythm_v1 import DEFAULT_THRESHOLDS_PCT
from canonical_market_bars_v2 import CanonicalMarketBarStoreV2
from instrument_registry_v2 import list_subscribed_sources_v2
from market_rhythm_dashboard_v1 import (
    DURATION_BUCKETS,
    amplitude_duration_counts_v1,
    build_rhythm_view_v1,
    cross_scale_alignment_v1,
    duration_bucket_v1,
    last_confirmed_legs_v1,
    turn_table_v1,
    empirical_fractal_motif_v1,
    recursively_generated_fractal_v1,
)

st.set_page_config(page_title="Markedsrytme · PriceGauger", page_icon="〰️", layout="wide")
st.title("Markedsrytme")
st.caption(
    "Levende, skrivebeskyttet observatorium for bekreftede svingninger. "
    "Samme kanoniske 1m-markedsdata som Strategy Scoreboard. "
    "Ingen ordre, ingen automatiske strategivalg."
)

try:
    sources = list_subscribed_sources_v2(provider="saxo")
except Exception as exc:
    st.error(f"Kunne ikke lese aktive instrumenter: {type(exc).__name__}")
    st.stop()

# No market-name-only joins; include the provider identity to prevent mixing
# different instruments with similar display labels.
candidates = tuple(sorted(sources, key=lambda x: (x.market_name, x.instrument_id)))
if not candidates:
    st.warning("Ingen aktive Saxo-instrumenter med innsamling. Aktiver instrumentet i TradingDesk først.")
    st.stop()

def _source_label(source):
    return f"{source.market_name} · {source.display_name} · UIC {source.provider_instrument_id}"

default_index = next((i for i, x in enumerate(candidates) if "tech 100" in x.market_name.lower()), 0)
c1, c2, c3 = st.columns([3, 1, 1])
with c1:
    selected = st.selectbox(
        "Marked / konkret instrument", candidates, index=default_index,
        format_func=_source_label, key="rhythm-market-instrument",
    )
with c2:
    window = st.selectbox("Analysevindu", ("6t", "24t", "7d"), index=1, key="rhythm-window")
with c3:
    threshold = st.selectbox(
        "Bekreftet reversering (indeks %)",
        DEFAULT_THRESHOLDS_PCT, index=3,
        format_func=lambda n: f"{n:g} %",
        key="rhythm-reversal-threshold",
    )

st.caption(
    "Automatisk avlesning hvert 30. sekund; nye *ferdiglukkede 1m-barer* "
    "gir oppdaterte rytmer. Topper/bunner er markert på historisk tidspunkt "
    "men kan først brukes etter senere bekreftelse."
)


@st.cache_data(ttl=24, max_entries=18, show_spinner=False)
def _read_canonical_closes(instrument_id: int, hours: int) -> pd.Series:
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=int(hours))
    bars = CanonicalMarketBarStoreV2().load_instrument_range(
        instrument_id=int(instrument_id), start=start, end=end,
        limit=12_000,
    )
    if not bars:
        return pd.Series(dtype=float, index=pd.DatetimeIndex([], tz="UTC"))
    # Exact canonical timestamps are the only source. No forming candles and
    # no interpolation across missing minutes / closed sessions.
    series = pd.Series(
        [float(bar.close) for bar in bars],
        index=pd.to_datetime([bar.bar_time for bar in bars], utc=True),
        dtype=float,
    )
    return series


def _plot_price_with_turns(view, chosen_threshold: float):
    fig = go.Figure()
    series = view.prices
    fig.add_trace(go.Scatter(
        x=series.index, y=series.values, name="Ferdiglukkede 1m-priser",
        mode="lines", line=dict(color="#94a3b8", width=1.4),
    ))
    events = view.turns[chosen_threshold]
    for kind, color, symbol in (("PEAK", "#f97316", "triangle-down"),
                                ("TROUGH", "#22c55e", "triangle-up")):
        matching = [x for x in events if x.kind == kind][-120:]
        if not matching:
            continue
        fig.add_trace(go.Scatter(
            x=[x.pivot_at for x in matching],
            y=[x.price for x in matching],
            mode="markers", name="TOPP" if kind == "PEAK" else "BUNN",
            marker=dict(color=color, symbol=symbol, size=9, line=dict(width=1, color="#0f172a")),
            customdata=[
                [x.confirmed_at.strftime("%d.%m %H:%M UTC"),
                 round((x.confirmed_at - x.pivot_at).total_seconds()/60,1)]
                for x in matching
            ],
            hovertemplate="Pivot: %{x}<br>Pris: %{y:.4f}<br>Først bekreftet: %{customdata[0]}<br>Forsinkelse: %{customdata[1]} min<extra></extra>",
        ))
    fig.update_layout(
        title="Pris og bekreftede vendepunkter (pivot vises retrospektivt)",
        height=355, margin=dict(t=50,b=20,l=15,r=15),
        legend=dict(orientation="h", y=-0.13), uirevision=f"price-{chosen_threshold}",
    )
    return fig


def _plot_duration(view):
    x = list(DURATION_BUCKETS)
    fig = go.Figure()
    for profile in view.profiles:
        vals = [
            profile.leg_duration_1m,
            profile.leg_duration_2m,
            profile.leg_duration_3_to_4m,
            profile.leg_duration_5_to_8m,
            sum(1 for leg in view.legs if leg.threshold_pct == profile.threshold_pct
                and 8 < leg.duration_minutes <= 20),
            sum(1 for leg in view.legs if leg.threshold_pct == profile.threshold_pct
                and leg.duration_minutes > 20),
        ]
        fig.add_trace(go.Bar(x=x,y=vals,name=f"{profile.threshold_pct:g} %"))
    fig.update_layout(
        title="Antall halvsykluser per tidslengde og reverseringsterskel",
        barmode="group", height=340, margin=dict(t=45,b=25,l=10,r=5),
        xaxis_title="Topp ↔ bunn (min)",yaxis_title="Antall",
        legend=dict(orientation="h",y=-0.25),
        uirevision="durations",
    )
    return fig


def _plot_heatmap(view):
    matrix = amplitude_duration_counts_v1(view)
    fig = go.Figure(data=go.Heatmap(
        z=matrix.values, x=list(matrix.columns),y=list(matrix.index),
        colorscale="Viridis",colorbar=dict(title="Antall"),
        hovertemplate="Amplitude: %{y}<br>Varighet: %{x}<br>Antall: %{z}<extra></extra>",
    ))
    fig.update_layout(
        title="Amplitude × varighet: én basis-svingserie (unngår dobbelttelling)",
        height=330, margin=dict(t=50,b=45,l=15,r=15),
        xaxis_title="Minutter (halvsyklus)", yaxis_title="Amplitude i indeks",
        uirevision="heatmap",
    )
    return fig


def _plot_amplitude_velocity(view, threshold_pct: float):
    legs = [leg for leg in view.legs if leg.threshold_pct == threshold_pct][-500:]
    fig = go.Figure()
    for direction, color in (("OPP", "#22c55e"), ("NED", "#f97316")):
        part = [leg for leg in legs if leg.direction == direction]
        fig.add_trace(go.Scatter(
            x=[leg.duration_minutes for leg in part],
            y=[leg.amplitude_pct for leg in part],
            mode="markers",name=direction,
            marker=dict(color=color,opacity=0.68,size=8),
            customdata=[round(leg.speed_pct_per_min,4) for leg in part],
            hovertemplate="Tid: %{x:.1f}m<br>Amplitude: %{y:.3f}%<br>Hastighet: %{customdata:.4f}%/min<extra></extra>",
        ))
    fig.update_layout(
        title="Hvor raskt beveger markedet seg? Varighet × amplitude",
        height=335,margin=dict(t=50,b=35,l=20,r=10),
        xaxis_title="Topp ↔ bunn (min)",yaxis_title="Amplitude (%)",
        legend=dict(orientation="h",y=-0.23),uirevision="velocity",
    )
    return fig


def _plot_nested_scales(view):
    fig = go.Figure()
    for level in sorted(view.turns):
        events = view.turns[level][-90:]
        if not events:
            continue
        fig.add_trace(go.Scatter(
            x=[turn.pivot_at for turn in events],
            y=[level for _ in events], mode="lines+markers",
            name=f"{level:g} %",
            line=dict(width=1, shape="hv"),
            marker=dict(size=8, symbol=["triangle-down" if x.kind=="PEAK" else "triangle-up" for x in events]),
            customdata=[turn.confirmed_at.strftime("%d.%m %H:%M UTC") for turn in events],
            hovertemplate="Pivot %{x}<br>Skala %{y}%<br>Bekreftet %{customdata}<extra></extra>",
        ))
    fig.update_layout(
        title="Fraktal svingstige – nestede vendepunkter per terskel",
        height=370,margin=dict(t=55,b=25,l=20,r=5),
        xaxis_title="Markedstid",yaxis_title="Minste reversering (%)",
        legend=dict(orientation="h",y=-0.18),uirevision="nesting",
    )
    return fig


def _plot_market_generated_fractal(motif, depth: int):
    """Observed normalized motifs vs recursive synthetic extrapolation of shape.

    X is normalized elapsed time INSIDE a completed macro swing, not a time
    forecast. Y is its normalized signed displacement, not future price.
    """
    fig=go.Figure()
    for i, sample in enumerate(motif.samples):
        fig.add_trace(go.Scatter(
            x=motif.x,y=sample,mode="lines",
            line=dict(color="rgba(148,163,184,0.23)",width=1),
            name="Observerte svingmotiv",showlegend=i==0,
            hovertemplate="Normalisert tid %{x:.2f}<br>Relativ pris %{y:.2f}<extra></extra>",
        ))
    fig.add_trace(go.Scatter(
        x=motif.x,y=motif.motif_y,mode="lines+markers",
        name="Median av observerte motiv",
        line=dict(color="#0ea5e9",width=3),
        marker=dict(size=5),
    ))
    generated_x,generated_y=recursively_generated_fractal_v1(motif,depth=depth)
    fig.add_trace(go.Scatter(
        x=generated_x,y=generated_y,mode="lines",
        name=f"GENERERT rekursiv fraktal (dybde {depth})",
        line=dict(color="#c084fc",width=2),
        hovertemplate="Normalisert tid %{x:.3f}<br>Syntetisk form %{y:.3f}<extra></extra>",
    ))
    fig.update_layout(
        title="Datadrevet fraktal: faktiske mikromotiv → syntetisk rekursjon",
        height=460,margin=dict(t=55,b=50,l=20,r=10),
        xaxis_title="Relativ tid mellom bekreftede makro-pivoter (0–1)",
        yaxis_title="Normalisert prisforløp i historiske makrobevegelser",
        legend=dict(orientation="h",y=-0.24),
        uirevision=f"empirical-fractal-{depth}",
    )
    return fig


@st.fragment(run_every="30s")
def _render_live() -> None:
    try:
        hours = {"6t":6,"24t":24,"7d":168}[window]
        closes = _read_canonical_closes(int(selected.instrument_id),hours)
        if len(closes) < 8:
            st.info("Venter på tilstrekkelige ferdiglukkede 1m-barer fra den valgte Saxo-kilden.")
            return
        view = build_rhythm_view_v1(closes,window=window)
    except Exception as exc:
        st.warning(f"Rytmevisning kan ikke oppdateres akkurat nå ({type(exc).__name__}). Ingen handelsfunksjoner påvirkes.")
        return

    age = max(0.0,(datetime.now(timezone.utc)-view.as_of.to_pydatetime()).total_seconds()/60)
    st.caption(f"Siste ferdige bar: {view.as_of:%d.%m.%Y %H:%M UTC} · {len(view.prices)} datapunkter · datakilde {selected.provider}:{selected.provider_instrument_id}")
    if age > 3:
        st.warning(
            f"Datakilde er {age:.0f} minutter gammel. Markedet kan være stengt "
            "eller datastrømmen forsinket. Ikke tolk gamle vendinger som LIVE-signaler."
        )

    profile = next(p for p in view.profiles if p.threshold_pct == float(threshold))
    events = view.turns[float(threshold)]
    last = events[-1] if events else None
    groups = st.columns(4)
    groups[0].metric("Median topp–bunn", f"{profile.median_leg_minutes:g} min" if profile.median_leg_minutes is not None else "ukjent")
    groups[1].metric("Median helsyklus", f"{profile.median_cycle_minutes:g} min" if profile.median_cycle_minutes is not None else "ukjent")
    groups[2].metric("Amplitude (median)", f"{profile.median_leg_amplitude_pct:.3f} %" if profile.median_leg_amplitude_pct is not None else "ukjent")
    groups[3].metric("Vendinger/observasjonstime", f"{profile.turns_per_hour:.1f}")
    groups = st.columns(4)
    groups[0].metric("Siste bekreftede", "TOPP" if last and last.kind=="PEAK" else "BUNN" if last else "ingen")
    groups[1].metric("Topp/bunn-forsinkelse",f"{(last.confirmed_at-last.pivot_at).total_seconds()/60:.1f} min" if last else "ukjent")
    groups[2].metric("Periodestabilitet (CV)",f"{profile.cycle_period_cv:.2f}" if profile.cycle_period_cv is not None else "ukjent")
    groups[3].metric("Fullførte sykluser",str(profile.completed_cycles))
    st.caption("CV nær 0 = mer stabil *historisk* periodetid; «ukjent» ved for få sykluser. Dette er ikke en prediksjon.")

    st.plotly_chart(_plot_price_with_turns(view,float(threshold)),use_container_width=True,config={"displaylogo":False})
    tab1,tab2,tab3,tab4 = st.tabs(("Sykluser og amplitude","Fraktal struktur","Vendinger og detaljer","Datadrevet fraktal"))
    with tab1:
        a,b = st.columns(2)
        with a: st.plotly_chart(_plot_duration(view),use_container_width=True,config={"displaylogo":False})
        with b: st.plotly_chart(_plot_heatmap(view),use_container_width=True,config={"displaylogo":False})
        st.plotly_chart(_plot_amplitude_velocity(view,float(threshold)),use_container_width=True,config={"displaylogo":False})
        st.caption(
            "Heatmap teller kun svingninger ved minste terskel; "
            "histogrammet teller separate definisjoner ved hver terskel. "
            "Rask nedgang kan sammenlignes med rask oppgang i hastighetsdiagrammet."
        )
    with tab2:
        st.plotly_chart(_plot_nested_scales(view),use_container_width=True,config={"displaylogo":False})
        st.dataframe(cross_scale_alignment_v1(view),hide_index=True,use_container_width=True)
        st.caption(
            "Fraktal samstemthet: antall større bekreftede vendinger med en tidligere "
            "bekreftet vending i samme retning på naboskala. Dette er *beskrivende* "
            "ettertidssammenfall, ikke en forutsigelse eller kausal sammenheng."
        )
        st.info(
            "Hypotese for senere PAPER-test: Kan tidspunkt, varighet og fart i små svingninger "
            "forutsi størrelsen eller fasen i større svingninger bedre enn en enkel baseline? "
            "Krever tidskausal walk-forward-validering og virkelige Saxo-kostnader."
        )
    with tab4:
        st.subheader("Fraktal generert fra observerte markedssvingninger")
        st.caption(
            "Dette er ikke tilfeldig fraktalkunst: først normaliseres ferdigbekreftede "
            "store topp–bunn-bevegelser. Mindre svingpunkter inne i hver større bevegelse "
            "danner et empirisk motiv. Medianmotivet blir så gjentatt rekursivt."
        )
        left,right=st.columns(2)
        with left:
            selected_levels=st.selectbox(
                "Mikro / makro (min. reversering %)",
                ((0.05,0.15),(0.05,0.35),(0.10,0.35),(0.15,0.35)),
                index=0,
                format_func=lambda levels:f"{levels[0]:g}% inne i {levels[1]:g}%",
                key=f"fractal-levels:{selected.instrument_id}",
            )
        with right:
            depth=st.slider(
                "Generert rekursjonsdybde",min_value=1,max_value=3,value=2,
                key=f"fractal-depth:{selected.instrument_id}",
            )
        motif=empirical_fractal_motif_v1(
            view,micro_threshold=selected_levels[0],
            macro_threshold=selected_levels[1],max_motifs=12,
        )
        if motif is None:
            st.info(
                "For lite datagrunnlag: trenger minst ett bekreftet stort swing "
                "med minst to mindre bekreftede vendepunkter inni. "
                "Prøv et lengre vindu eller lavere makroterskel."
            )
        else:
            x1,x2,x3=st.columns(3)
            x1.metric("Observerte makro-motiv",motif.sample_count)
            x2.metric("Median formspredning",f"{motif.median_dispersion:.3f}")
            x3.metric("Rekursjonsdybde",depth)
            if motif.sample_count<3:
                st.warning("Færre enn tre observerte motiver: fraktalformen er foreløpig svært usikker.")
            st.plotly_chart(
                _plot_market_generated_fractal(motif,depth),
                use_container_width=True,config={"displaylogo":False},
            )
            st.caption(
                "Grå = faktiske historiske, normaliserte svingforløp. Blå = median "
                "av dem. Lilla = syntetisk, rekursivt generert motiv. Den lilla "
                "kurven er *ikke* markedsdata, prisprognose eller handels-signal. "
                "Formspredning er beskrivende variasjon, ikke et validert regimesignal."
            )
    with tab3:
        st.subheader("Siste bekreftede topper og bunner")
        st.dataframe(turn_table_v1(view,threshold_pct=float(threshold)),hide_index=True,use_container_width=True)
        st.subheader("Tid og hastighet mellom påfølgende topper/bunner")
        st.dataframe(last_confirmed_legs_v1(view,threshold_pct=float(threshold)),hide_index=True,use_container_width=True)
        st.caption(
            "Pivot kan vises på historisk tidspunkt, men var først kjent ved «Bekreftet». "
            "En fremtidig strategi må bruke bekreftelsestid og deretter faktisk broker-fill."
        )

_render_live()

with st.expander("Metode, usikkerhet og videre fraktal forskning", expanded=False):
    st.markdown(
        "Bruker en eksisterende kanonisk 1m-sluttkursfeed. "
        "0,05–3 % bekreftelsesgrenser skaper seks samtidige sving-skalaer. "
        "Hull i prisfeed bryter syklusene; ufullførte sykluser gis ingen varighet. "
        "Ingen sekundbaserte topper eller årssykluser kan måles her med nåværende "
        "innsamling og valgt vindu. Alle grafer er tilbakeblikk. "
        "Neste steg er en frosset fremoverrettet fraktal PAPER-modell og "
        "kobling til faktisk LIVE-strategiversjon, Saxo-fill og netto P/L. "
        "Inntil da er samvariasjon på tvers av skalaer en **testbar hypotese**, ikke bevist edge."
    )
