from __future__ import annotations

from datetime import timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from config import twelve_data_api_key
from decision_engine import build_market_assessment
from market_data import MarketRequest, TwelveDataProvider, YahooProvider, fetch_market_data
from trajectory_forecast import TradePlan, build_trade_plan, update_plan_status


st.set_page_config(page_title="Trajectory Forecast", page_icon="🧭", layout="wide")

ASSETS = {
    "Brent": {"yahoo": "BZ=F"},
    "Silver": {"twelve": "XAG/USD", "yahoo": "SI=F"},
    "Gold": {"twelve": "XAU/USD", "yahoo": "GC=F"},
    "DXY": {"yahoo": "DX-Y.NYB"},
}


def _fmt(value: float | None) -> str:
    if value is None:
        return "—"
    if abs(value) >= 100:
        return f"{value:,.2f}"
    return f"{value:.4f}"


def _plan_from_state(record: dict) -> TradePlan:
    from trajectory_forecast import TrajectoryPoint

    data = dict(record)
    data["trajectory"] = [TrajectoryPoint(**point) for point in data.get("trajectory", [])]
    return TradePlan(**data)


def _exit_guidance(plan: TradePlan, status: str, current_price: float) -> str:
    if status == "NO_TRADE":
        return "Ingen posisjon. Vent på et nytt målbart signal."
    if status == "INVALIDATED":
        return "Exit nå: den opprinnelige hypotesen er ugyldiggjort."
    if status == "TARGET_2_HIT":
        return "Full exit eller svært stram trailing: hovedmålet er nådd."
    if status == "TARGET_1_HIT":
        return "Sikre delgevinst og flytt evaluert exit mot inngang eller siste lokale sving."
    if status == "ENTRY_ZONE":
        return "Inngangssonen er aktiv. Krev bekreftelse i forventet retning før manuell inngang."
    if status in {"WAITING_FOR_PULLBACK", "BELOW_ENTRY_ZONE", "ABOVE_ENTRY_ZONE"}:
        return "Ikke jag prisen. Planen er ikke aktivert på riktig måte ennå."
    return f"Observer videre. Nåværende pris: {_fmt(current_price)}."


st.title("Trajectory Forecast")
st.caption(
    "Konkret, testbar forecast med inngang, ugyldiggjøring, mål og mulige prisbaner. "
    "Usikkerhetsområdet utvides fremover i tid og skaleres med signalets kvalitet og observert volatilitet."
)

with st.sidebar:
    st.header("Forecast-oppsett")
    asset = st.selectbox("Instrument", list(ASSETS))
    interval = st.selectbox("Prisintervall", ["5min", "15min", "30min", "1h"], index=0)
    outputsize = st.selectbox("Prisbarer", [300, 500, 1000, 2000], index=1)
    provider_choice = st.selectbox("Prisleverandør", ["Automatisk", "Twelve Data", "Yahoo Finance"])
    response_role = st.selectbox(
        "Responsrolle",
        ["UNCLASSIFIED", "LEADER", "CONFIRMING", "LAGGING", "EXHAUSTED", "DECOUPLED"],
        index=3,
    )
    response_window = st.selectbox("Forventet responsvindu", ["5–20 min", "15–60 min", "30–120 min", "1–4 timer"], index=1)
    if st.button("Oppdater marked", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

request = MarketRequest(asset_name=asset, interval=interval, outputsize=outputsize, symbols=ASSETS[asset])
providers_all = [TwelveDataProvider(twelve_data_api_key()), YahooProvider()]
providers = providers_all
if provider_choice == "Twelve Data":
    providers = [providers_all[0]]
elif provider_choice == "Yahoo Finance":
    providers = [providers_all[1]]

try:
    result = fetch_market_data(request, providers)
    market = result.frame.copy()
    provider_name = result.provider_name
except Exception as exc:
    st.error(f"Kunne ikke hente markedsdata: {exc}")
    st.stop()

if market.empty:
    st.warning("Ingen markedsdata tilgjengelig.")
    st.stop()

market["timestamp"] = pd.to_datetime(market["timestamp"], utc=True, errors="coerce")
market["close"] = pd.to_numeric(market["close"], errors="coerce")
market = market.dropna(subset=["timestamp", "close"]).sort_values("timestamp")
current_price = float(market["close"].iloc[-1])

# This page accepts the existing Combined/Decision output when present, but also
# remains demonstrable from current momentum when the other modules have not run.
assessment = build_market_assessment(
    asset=asset,
    messages=pd.DataFrame(),
    market=market,
    intraday_reactions=st.session_state.get("gdelt_intraday_reactions", []),
)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Instrument", asset)
c2.metric("Siste pris", _fmt(current_price))
c3.metric("Analyseretning", assessment.direction)
c4.metric("Konfidens", f"{assessment.confidence_pct:.1f} %")
st.caption(f"Datakilde: {provider_name} · Forecasten bruker eksisterende beslutningsoutput og siste observerte prisstruktur.")

control_1, control_2, control_3 = st.columns([1, 1, 2])
with control_1:
    manual_direction = st.selectbox(
        "Retning til test",
        ["AUTO", "LONG", "SHORT", "NEUTRAL"],
        help="AUTO bruker eksisterende assessment. Manuell retning gjør det mulig å teste graf og livsløp før Combined-signalet er ferdig kalibrert.",
    )
with control_2:
    manual_move = st.number_input(
        "Forventet totalbevegelse (%)",
        min_value=0.0,
        max_value=20.0,
        value=float(abs(assessment.expected_move_pct or max(abs(assessment.momentum_pct or 0.0), 0.25))),
        step=0.05,
    )
with control_3:
    confidence_override = st.slider(
        "Signalkvalitet / konfidens",
        0,
        95,
        int(round(assessment.confidence_pct)),
        help="Lavere kvalitet gir et bredere område av mulige fremtidige prisbaner.",
    )

selected_direction = assessment.direction if manual_direction == "AUTO" else manual_direction
plan_key = f"trajectory_plan::{asset}"

if st.button("Opprett og lås ny testforecast", type="primary", use_container_width=True):
    plan = build_trade_plan(
        instrument=asset,
        market=market,
        direction=selected_direction,
        confidence_pct=float(confidence_override),
        expected_move_pct=float(manual_move),
        rationale=assessment.rationale,
        response_role=response_role,
        expected_response_window=response_window,
    )
    st.session_state[plan_key] = plan.to_record()
    st.session_state[f"{plan_key}::observations"] = []

if plan_key not in st.session_state:
    st.info("Opprett en testforecast for å låse inngang, invalidasjon og mål mot dagens markedssnapshot.")
    st.stop()

plan = _plan_from_state(st.session_state[plan_key])
status = update_plan_status(plan, current_price)
observations_key = f"{plan_key}::observations"
observations = st.session_state.setdefault(observations_key, [])
now = pd.Timestamp.now(tz="UTC")
if not observations or observations[-1]["price"] != current_price:
    observations.append({"timestamp": now.isoformat(), "price": current_price, "status": status})
    del observations[:-250]

st.subheader(f"{plan.instrument} · {plan.setup}")

m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Status", status)
m2.metric("Inngangssone", f"{_fmt(plan.entry_low)}–{_fmt(plan.entry_high)}")
m3.metric("Ugyldiggjøring", _fmt(plan.invalidation_price))
m4.metric("Mål 1", _fmt(plan.target_1))
m5.metric("Mål 2", _fmt(plan.target_2))

st.markdown(
    f"**Aktivering:** {_fmt(plan.activation_price)} · "
    f"**Inngangsvindu:** {plan.entry_window} · "
    f"**Målvindu:** {plan.target_window} · "
    f"**Forecast utløper uten aktivering etter:** {plan.expires_after_minutes} min"
)
st.info(_exit_guidance(plan, status, current_price))

last_timestamp = market["timestamp"].iloc[-1]
future_times = [last_timestamp + timedelta(minutes=point.minutes_ahead) for point in plan.trajectory]
expected_prices = [plan.reference_price * (1 + point.expected_pct / 100) for point in plan.trajectory]
lower_prices = [plan.reference_price * (1 + point.lower_pct / 100) for point in plan.trajectory]
upper_prices = [plan.reference_price * (1 + point.upper_pct / 100) for point in plan.trajectory]

fig = go.Figure()
history = market.tail(min(180, len(market)))
fig.add_trace(go.Scatter(x=history["timestamp"], y=history["close"], mode="lines", name="Observert pris"))
fig.add_trace(
    go.Scatter(
        x=future_times + future_times[::-1],
        y=upper_prices + lower_prices[::-1],
        fill="toself",
        fillcolor="rgba(128,128,128,0.18)",
        line=dict(color="rgba(128,128,128,0)"),
        hoverinfo="skip",
        name="Mulig baneområde",
    )
)
fig.add_trace(
    go.Scatter(
        x=future_times,
        y=expected_prices,
        mode="lines+markers",
        line=dict(dash="dash"),
        name="Sentral forventet bane",
    )
)

for label, value, dash in [
    ("Inngang lav", plan.entry_low, "dot"),
    ("Inngang høy", plan.entry_high, "dot"),
    ("Ugyldig", plan.invalidation_price, "dash"),
    ("Mål 1", plan.target_1, "dash"),
    ("Mål 2", plan.target_2, "dash"),
]:
    if value is not None:
        fig.add_hline(y=value, line_dash=dash, annotation_text=label, annotation_position="top left")

fig.update_layout(
    height=620,
    margin=dict(l=10, r=10, t=30, b=10),
    legend=dict(orientation="h"),
    xaxis_title="Tid",
    yaxis_title=asset,
    hovermode="x unified",
)
st.plotly_chart(fig, use_container_width=True)

left, right = st.columns([1.2, 1])
with left:
    st.markdown("### Forventet sekvens")
    st.write(" → ".join(plan.expected_path))
    st.markdown("### Begrunnelse")
    for reason in plan.rationale:
        if reason:
            st.write(f"• {reason}")

with right:
    st.markdown("### Fortløpende lifecycle")
    observation_frame = pd.DataFrame(observations)
    if not observation_frame.empty:
        observation_frame["timestamp"] = pd.to_datetime(observation_frame["timestamp"], utc=True).dt.strftime("%H:%M:%S UTC")
        st.dataframe(observation_frame.tail(20), use_container_width=True, hide_index=True)
    if st.button("Slett låst forecast", use_container_width=True):
        st.session_state.pop(plan_key, None)
        st.session_state.pop(observations_key, None)
        st.rerun()

with st.expander("Maskinlesbar forecast"):
    st.json(plan.to_record())
