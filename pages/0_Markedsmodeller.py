"""Read-only model hub for quantized market structure and coupled strings.

Manual research on exact subscribed Saxo instrument IDs. No account access,
broker writes, strategy switching, scheduling or LIVE recommendations.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import streamlit as st

from canonical_market_bars_v2 import CanonicalMarketBarStoreV2
from instrument_registry_v2 import list_subscribed_sources_v2
from market_instrument_ensemble_v1 import ensemble_report
from market_models_state_v1 import (
    MARKET_MODEL_CATALOG_V1,
    RHYTHM_LABELS,
    TREND_LABELS,
    market_state_history_v1,
)
from market_rhythm_research_v1 import clean_bars


st.set_page_config(page_title="Markedsmodeller · PriceGauger", page_icon="🎼", layout="wide")
st.title("Markedsmodeller")
st.caption(
    "Felles arbeidsrom for modeller av markedstilstander, samspill og senere "
    "kalibrerte prognoser. Kun manuell PAPER-forskning på ferdiglukkede 1m-priser. "
    "Ingen endring av AutoTrader eller aktive kontoer."
)


@st.cache_data(ttl=600, max_entries=32, show_spinner=False)
def _load_canonical_closes(instrument_id: int, days: int) -> pd.Series:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    rows = CanonicalMarketBarStoreV2().load_instrument_range(
        instrument_id=int(instrument_id),
        start=start,
        end=end,
        limit=days * 24 * 60 + 10,
    )
    # An in-progress candle may be present in physical storage; it must never
    # be used as a completed observation before its UTC minute has ended.
    completed = tuple(row for row in clean_bars(rows)
                      if row.at + timedelta(minutes=1) <= end)
    return pd.Series(
        [row.close for row in completed],
        index=pd.to_datetime([row.at for row in completed], utc=True),
        dtype=float,
    )


def _label(source) -> str:
    return f"{source.market_name} · {source.display_name} · Saxo UIC {source.provider_instrument_id}"


try:
    instruments = tuple(sorted(
        list_subscribed_sources_v2(provider="saxo"),
        key=lambda source: (source.market_name, source.instrument_id),
    ))
except Exception as exc:
    st.error(f"Instrumentregisteret kunne ikke leses ({type(exc).__name__}).")
    st.stop()

if not instruments:
    st.info("Ingen aktive Saxo-instrumenter samles inn. Velg abonnementer fra TradingDesk først.")
    st.stop()

st.subheader("1 · Modell og datagrunnlag")
with st.form("market-models-run-v1"):
    c1, c2 = st.columns([3, 1])
    with c1:
        selected_model = st.selectbox(
            "Modell", MARKET_MODEL_CATALOG_V1,
            format_func=lambda model: f"{model.name} · {model.status}",
        )
        primary = st.selectbox(
            "Hovedinstrument (eksakt UIC)", instruments,
            index=next((i for i, s in enumerate(instruments) if "tech 100" in s.market_name.lower()), 0),
            format_func=_label,
        )
    with c2:
        days = st.selectbox("Kanonisk historikk", (7, 14, 30), index=0,
                            format_func=lambda d: f"{d} dager")
    peers = st.multiselect(
        "Andre strenger – valgfritt (maks 7)",
        tuple(s for s in instruments if s.instrument_id != primary.instrument_id),
        format_func=_label, max_selections=7,
        help="Identiske UTC-minutter sammenlignes uten interpolering eller hullfylling.",
    )
    st.caption(
        "Samme faste 3×3-kvantisering for alle markeder: NED/SIDEVEIS/OPP × "
        "RASK/MIDDELS/LANGSOM. Amplitude måles separat og kontinuerlig. "
        "60 fullførte 1m-returer, hysterese og ingen tilstand over datahull."
    )
    run = st.form_submit_button("Analyser markedstilstander", type="primary")

if run:
    try:
        with st.spinner("Beregner kausale tilstander og samspill fra kanoniske 1m-barer …"):
            chosen = (primary, *peers)
            closes = {_label(source): _load_canonical_closes(int(source.instrument_id), days)
                      for source in chosen}
            histories = {name: market_state_history_v1(series)
                         for name, series in closes.items()}
            interactions = ensemble_report(closes, target=_label(primary)) if len(closes) >= 2 else None
            st.session_state["market-models-state-v1-result"] = {
                "model": selected_model.key,
                "primary": _label(primary),
                "days": days,
                "closes": {name: {"count": len(series),
                                  "last_bar": series.index[-1] if len(series) else None}
                           for name, series in closes.items()},
                "histories": histories,
                "interactions": interactions,
                "computed": datetime.now(timezone.utc),
            }
    except Exception as exc:
        st.error(f"Analysen stoppet ({type(exc).__name__}). Ingen data ble skrevet.")

result = st.session_state.get("market-models-state-v1-result")
if result:
    st.divider()
    st.subheader("2 · Kvantiserte markedstilstander")
    st.caption(
        f"Resultat fra {result['computed']:%d.%m.%Y %H:%M UTC} · "
        f"{result['days']} kalenderdager · {len(result['closes'])} eksakte Saxo-instrumenter. "
        "Historiske målinger, ikke sanntidsprognoser."
    )
    snapshots = []
    for name, info in result["closes"].items():
        states = result["histories"][name]
        current = states[-1] if states and states[-1].bar_at == info["last_bar"] else None
        snapshots.append({
            "Instrument": name,
            "Fullførte 1m-barer": info["count"],
            "Siste bar UTC": info["last_bar"],
            "Alder på data (min)": (round((result["computed"] - info["last_bar"].to_pydatetime()
                                          - timedelta(minutes=1)).total_seconds() / 60, 1)
                                      if info["last_bar"] is not None else None),
            "Tilstand (siste gyldige 60m)": current.state_key if current else "UKJENT",
            "Retningseffektivitet": round(current.efficiency, 3) if current else None,
            "60m endring %": round(current.net_change_pct, 3) if current else None,
            "1m volatilitet %": round(current.volatility_pct_1m, 4) if current else None,
            "Median rytme min": current.median_run_minutes if current else None,
            "Rytmebelegg": current.rhythm_evidence if current else "MANGLER",
        })
    st.dataframe(snapshots, hide_index=True, use_container_width=True)
    st.caption(
        "UKJENT betyr manglende sammenhengende 61 barer eller manglende prisbevegelse, "
        "ikke et kjøps-/salgsignal. LANGSOM med svakt rytmebelegg er ikke en påvist syklus. "
        "Siste bar kan være gammel når børsen er stengt eller datastrømmen har stoppet."
    )

    target_states = result["histories"][result["primary"]]
    if target_states:
        c1, c2 = st.columns([2, 3])
        with c1:
            st.markdown("**Tilstandsfordeling (historisk)**")
            counts = pd.Series([s.state_key for s in target_states]).value_counts()
            distribution = pd.DataFrame([
                {"Trend": trend, "Rytme": rhythm,
                 "Antall avlesninger": int(counts.get(f"{trend}/{rhythm}", 0))}
                for trend in TREND_LABELS for rhythm in RHYTHM_LABELS
            ])
            st.dataframe(distribution, hide_index=True, use_container_width=True)
        with c2:
            st.markdown("**Siste tilstandsskifter (5-minutters avlesning)**")
            last_states = target_states[-160:]
            timeline = pd.DataFrame([
                {"Kjent fra UTC": state.as_of,
                 "Tilstand": state.state_key,
                 "Effektivitet": round(state.efficiency, 3),
                 "Amplitude (1m σ %)": round(state.volatility_pct_1m, 4),
                 "Halvperiode min": state.median_run_minutes,
                 "Rytmebelegg": state.rhythm_evidence}
                for state in last_states
            ])
            st.dataframe(timeline.iloc[::-1], hide_index=True, use_container_width=True,
                         height=380)
        st.caption(
            "Avlesningene bygger på overlappende 60m-vinduer, er ikke uavhengige "
            "statistiske forsøk og er ikke en validert strategi-fordel. "
            "Våre 1m-barer kan ikke avsløre sekunders intrabar-topper/bunner."
        )
    else:
        st.warning("Ingen sammenhengende 60m-vinduer i valgt historikk. Tilstand = UKJENT.")

    st.subheader("3 · Interaksjoner mellom strenger")
    coupled = result["interactions"]
    if coupled:
        st.markdown("**Retnings- og aktivitetskoblinger**")
        st.dataframe(coupled["couplings"], hide_index=True, use_container_width=True)
        st.markdown("**Endrer koblingen seg med tilstand/aktivitet?**")
        st.dataframe(coupled["regimes"], hide_index=True, use_container_width=True)
        with st.expander("Frekvens-koherens, felles faktor og holdout-kontroller"):
            st.dataframe(coupled["coherence"], hide_index=True, use_container_width=True)
            if coupled["factor"]:
                st.write("Felles statistisk faktor (PCA):", coupled["factor"])
            else:
                st.info("For lite komplett felles datagrunnlag for PCA.")
            st.dataframe(coupled["leads"], hide_index=True, use_container_width=True)
            st.caption(
                "Sammenfall/koherens er ikke årsak eller handelssignal. "
                "Holdout-R² > 0 indikerer bedring mot en enkel treningsbaseline, "
                "men er ikke en kalibrert prisprognose eller nettoavkastning."
            )
    else:
        st.info("Legg til minst én annen streng for å måle samvariasjon og lead/lag.")

st.divider()
st.subheader("Videre modeller på samme fundament")
st.markdown(
    "1. **Patch-dynamikk:** tilstandsvarighet, overganger og samspill på flere skalaer.\n"
    "2. **Strategikartlegging:** PAPER-resultat og tapshaler betinget på tilstand, "
    "med kronologisk holdout.\n"
    "3. **Probabilistisk prognose:** fremtidige prisfordelinger og prediksjonsintervaller "
    "kalibrert på urørte data."
)
st.caption(
    "Ikke implementert i denne første modellen. Ingen automatisk tilpasning, "
    "strategibytte eller ordre aktiveres herfra."
)
