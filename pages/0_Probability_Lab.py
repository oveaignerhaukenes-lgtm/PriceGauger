"""Probability Lab: isolated as-of historical 1m forecasting research."""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import json

import pandas as pd
import streamlit as st

from canonical_market_bars_v2 import CanonicalMarketBarStoreV2
from instrument_registry_v2 import list_subscribed_sources_v2
from probability_lab_v1 import (
    HORIZONS, MAX_BARS, score_forecasts, up_calibration,
    walk_forward_probability,
)

st.set_page_config(page_title="Probability Lab · PriceGauger", layout="wide")
st.title("Probability Lab · 1m")
st.caption(
    "Stokastisk prisforskning: Markov versus rullerende frekvens og "
    "Poisson/Skellam-proxy. Ingen LIVE-autoritet, ingen Saxo-ordrer."
)
st.info(
    "Bruker kun lagrede, avsluttede 1-minutts OHLC fra eksakt Saxo-instrument. "
    "Grafens 1-sekunds oppdatering er ikke lagret tickhistorikk. "
    "Skellam her er en hypotese om antall grønne/røde 1m-hendelser, "
    "ikke en tickbasert Poisson-modell."
)
try:
    sources = list_subscribed_sources_v2(provider="saxo")
except Exception as exc:
    sources = ()
    st.warning("Kanonisk instrumentoversikt er utilgjengelig: " + type(exc).__name__)

if not sources:
    st.warning("Ingen abonnerte Saxo-instrumenter med kanonisk historikk er tilgjengelige.")
    st.stop()

markets = sorted({s.market_name for s in sources})
market = st.selectbox("Marked", markets, key="plab:market")
candidates = [x for x in sources if x.market_name == market]
source = st.selectbox(
    "Eksakt Saxo-produkt/UIC", candidates,
    format_func=lambda x: f"{x.display_name} · UIC {x.provider_instrument_id} · {x.asset_type or '?'}",
    key="plab:source",
)
a, b, c = st.columns(3)
horizon = a.selectbox("Prognosehorisont", HORIZONS, format_func=lambda x: f"{x} min", key="plab:h")
lag = b.selectbox("Markov-orden", (1, 2, 3), index=1, key="plab:lag")
window = c.selectbox("Historisk treningsvindu", (60, 120, 180, 360, 720), index=2,
                     format_func=lambda x: f"{x} ettminuttsbarer", key="plab:window")
a, b, c = st.columns(3)
hours = a.selectbox("Prøveperiode", (6, 12, 24, 48, 72, 168), index=2,
                    format_func=lambda x: f"{x} timer", key="plab:hours")
end_day = b.date_input("Sluttdato (UTC)", datetime.now(timezone.utc).date(), key="plab:date")
threshold = c.slider("Retningssignal ved sannsynlighet minst", .35, .90, .55, .05, key="plab:threshold")
roundtrip_bps = st.number_input(
    "Tenkt full tur/retur-kostnad (bps, kun hypotetiske signaler)",
    min_value=0., max_value=1000., value=8., step=1., key="plab:cost"
)
run_key = (int(source.instrument_id), str(end_day), int(hours),
           int(horizon), int(lag), int(window))
if st.button("Kjør kausal walk-forward på lagrede 1m-barer", type="primary", key="plab:run"):
    try:
        end = min(datetime.now(timezone.utc),
                  datetime.combine(end_day, datetime.max.time(), tzinfo=timezone.utc))
        start = end - timedelta(hours=int(hours))
        bars = CanonicalMarketBarStoreV2().load_instrument_range(
            instrument_id=source.instrument_id, start=start, end=end,
            limit=MAX_BARS + 1,
        )
        if len(bars) > MAX_BARS:
            raise ValueError("Mer enn 10000 barer: velg kortere prøveperiode.")
        if not bars:
            raise ValueError("Ingen lagrede 1m-barer for nøyaktig dette instrumentet og tidsrommet.")
        resolved, preview, gap_count = walk_forward_probability(
            bars, horizon=horizon, lag=lag, window=window,
        )
        if not resolved:
            raise ValueError(
                "For lite sammenhengende 1m-historikk. Velg lengre vindu eller et aktivt marked."
            )
        st.session_state["plab:result"] = {
            "key": run_key, "data": resolved, "preview": preview,
            "gaps": gap_count, "bars": len(bars),
            "start": start.isoformat(), "end": end.isoformat(),
            "instrument_id": int(source.instrument_id),
            "uic": str(source.provider_instrument_id),
            "market": str(source.market_name),
        }
    except (ValueError, TypeError, OverflowError) as exc:
        st.session_state.pop("plab:result", None)
        st.error("Kunne ikke kjøre testen: " + str(exc)[:300])
    except Exception as exc:
        st.session_state.pop("plab:result", None)
        st.error("Datakilde utilgjengelig: " + type(exc).__name__)

result = st.session_state.get("plab:result")
if result and result["key"] != run_key:
    st.warning("Parameterne er endret. Kjør testen på nytt for å unngå gamle resultater.")
elif result:
    forecast = result["data"]
    st.subheader("Walk-forward · historiske, tidligere usette utfall")
    st.caption(
        f"{result['market']} · Saxo UIC {result['uic']} · "
        f"{result['bars']} avsluttede barer · {result['gaps']} databrudd · "
        f"{len(forecast)} prognoser med observert fasit. "
        "Ingen prognose krysser databrudd. Treningsetiketter må allerede være ferdige ved as-of."
    )
    model_names = {"baseline": "Frekvens (baseline)",
                   "markov": "Markov (regularisert)",
                   "skellam": "Poisson/Skellam (1m-proxy)"}
    rows = []
    for model, title in model_names.items():
        score = score_forecasts(
            forecast, model, threshold=float(threshold),
            roundtrip_bps=float(roundtrip_bps),
        )
        rows.append({
            "Modell": title,
            "Prognoser": score["n"],
            "Brier (lav er bra)": round(score["brier"], 4),
            "Log-loss": round(score["log_loss"], 4),
            "Treff (3 klasser)": f"{100 * score['accuracy']:.1f}%",
            "Hypotetiske signaler": score["signals"],
            "Snittresultat per signal etter tenkt kost, %": (
                round(score["mean_signal_net_pct"], 4)
                if score["mean_signal_net_pct"] is not None else None
            ),
        })
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
    st.warning(
        "Signalresultat er KUN et uavhengig hypotetisk fremtidig close-til-close-avkastningsmål, "
        "ikke en eksekverbar strategi eller Saxo-fill. Horisonter over 1 min overlapper; "
        "verdiene kan ikke summeres eller tolkes som kapitalavkastning."
    )
    preview = result["preview"]
    if preview:
        st.subheader("Siste datatilgjengelige as-of-prognose · uten kjent fasit")
        st.caption(f"As-of {preview.asof} · {preview.horizon}m horisont. "
                   "Ikke et verifisert sanntidssignal dersom historikken er forsinket.")
        st.dataframe(pd.DataFrame([
            {"Modell": title,
             "Opp %": round(100 * getattr(preview, model)[0], 2),
             "Ned %": round(100 * getattr(preview, model)[1], 2),
             "Uendret %": round(100 * getattr(preview, model)[2], 2)}
            for model, title in model_names.items()
        ]), hide_index=True, use_container_width=True)
    st.subheader("Kalibrering av P(opp)")
    model_to_inspect = st.selectbox(
        "Undersøk modell", list(model_names),
        format_func=lambda x: model_names[x], key="plab:calibration_model",
    )
    cal = pd.DataFrame(up_calibration(forecast, model_to_inspect))
    if not cal.empty:
        st.dataframe(cal, hide_index=True, use_container_width=True)
        st.caption(
            "Hvis prognosene er kalibrerte, bør gjennomsnittlig predikert "
            "oppsannsynlighet ligge nær observert oppfrekvens i samme gruppe. "
            "Få datapunkter i en gruppe gir høy usikkerhet."
        )
    with st.expander("Siste 100 evaluerte prognoser"):
        st.dataframe(pd.DataFrame([{
            "As-of (UTC)": x.asof,
            "Mål-tid (UTC)": x.target,
            "P(opp)": round(getattr(x, model_to_inspect)[0], 4),
            "P(ned)": round(getattr(x, model_to_inspect)[1], 4),
            "P(flat)": round(getattr(x, model_to_inspect)[2], 4),
            "Fasit": x.actual,
            "Neste prisendring %": round(x.return_pct, 4),
            "Tilgjengelige treningsutfall": x.sample_size,
            "Samme Markov-tilstand": x.state_matches,
        } for x in forecast[-100:]), hide_index=True, use_container_width=True)
    package = {
        "schema": "PG_PROBABILITY_LAB_1M_V1",
        "instrument": {"id": result["instrument_id"], "uic": result["uic"],
                       "market": result["market"]},
        "utc_range": [result["start"], result["end"]],
        "settings": {"horizon_min": horizon, "markov_lag": lag, "window_bars": window,
                     "threshold": threshold, "hypothetical_roundtrip_bps": roundtrip_bps},
        "model_notes": ["Skellam is a minute-sign event proxy, NOT tick-Poisson.",
                        "No historical BBO, no Saxo fills, no LIVE orders.",
                        "Each forecast uses as-of resolved labels only.",
                        "Cost-adjusted signal payoff is not cumulative strategy P/L."],
        "gaps": result["gaps"],
        "forecast_rows": [asdict(p) for p in forecast],
        "latest_unresolved_preview": asdict(preview) if preview else None,
    }
    st.download_button(
        "Eksporter prognoser og fasit (JSON)",
        data=json.dumps(package, ensure_ascii=False, allow_nan=False),
        file_name="pricegauger_probability_lab_1m.json",
        mime="application/json", key="plab:export",
    )
else:
    st.caption("Velg et produkt og kjør walk-forward for å teste mot faktisk lagret historikk.")
