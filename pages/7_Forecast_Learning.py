from __future__ import annotations

from datetime import datetime

import plotly.graph_objects as go
import streamlit as st

from build_info import render_build_badge
from forecast_learning import ForecastOutcomeStore, realized_progress_path
from forecast_store import ForecastStore
from forecast_visuals import build_trajectory


st.set_page_config(page_title="Prognoselæring · PriceGauger", page_icon="🎯", layout="wide")
render_build_badge()
st.title("Prognoselæring")
st.caption(
    "Originale, frosne forecasts mot faktisk markedsutvikling. Denne siden evaluerer modellen; "
    "den endrer ikke historiske prognoser eller anbefalinger."
)

forecast_store = ForecastStore()
outcome_store = ForecastOutcomeStore()
forecasts = forecast_store.load_all(limit=1000)

if not forecasts:
    st.info("Ingen ForecastSnapshots er lagret ennå.")
    st.stop()

markets = sorted({item.market for item in forecasts})
market = st.selectbox("Marked", markets)
market_forecasts = forecast_store.load_all(market=market, limit=300)
outcomes = {item.forecast_id: item for item in outcome_store.load_all(market=market, limit=300)}

completed = [item for item in outcomes.values() if item.status == "COMPLETE"]
direction_scored = [item for item in completed if item.direction_hit is not None]
interval_scored = [item for item in completed if item.interval_hit is not None]

s1, s2, s3, s4 = st.columns(4)
s1.metric("Fullførte forecasts", len(completed))
s2.metric(
    "Retningstreff",
    "—" if not direction_scored else f"{100 * sum(bool(item.direction_hit) for item in direction_scored) / len(direction_scored):.0f}%",
)
s3.metric(
    "Innenfor intervall",
    "—" if not interval_scored else f"{100 * sum(bool(item.interval_hit) for item in interval_scored) / len(interval_scored):.0f}%",
)
s4.metric("Lagrede forecasts", len(market_forecasts))


def _label(item):
    stamp = datetime.fromisoformat(item.as_of.replace("Z", "+00:00"))
    return f"{stamp:%d.%m %H:%M} · {item.direction} · {item.status} · {item.confidence:.0%}"


forecast = st.selectbox("Forecast", market_forecasts, format_func=_label)
outcome = outcomes.get(forecast.forecast_id)

if forecast.reference_price is None or forecast.horizon_hours is None:
    st.warning("Denne forecasten mangler referansepris eller horisont og kan ikke tegnes mot faktisk utvikling ennå.")
    st.stop()

series = build_trajectory(forecast)
horizon = float(forecast.horizon_hours)


def _x(points):
    return [max(0.0, (x - 50.0) / 50.0) * horizon for x, _ in points]


def _y(points):
    return [y for _, y in points]


fig = go.Figure()
fig.add_trace(
    go.Scatter(
        x=_x(series.fan_lower),
        y=_y(series.fan_lower),
        mode="lines",
        line={"width": 0},
        hoverinfo="skip",
        showlegend=False,
        name="Nedre usikkerhet",
    )
)
fig.add_trace(
    go.Scatter(
        x=_x(series.fan_upper),
        y=_y(series.fan_upper),
        mode="lines",
        line={"width": 0},
        fill="tonexty",
        fillcolor="rgba(120,144,179,0.18)",
        hoverinfo="skip",
        name="Usikkerhetsfelt",
    )
)
fig.add_trace(
    go.Scatter(x=_x(series.bull), y=_y(series.bull), mode="lines", name="Bull", line={"color": "#2f9e64", "dash": "dot"})
)
fig.add_trace(
    go.Scatter(x=_x(series.bear), y=_y(series.bear), mode="lines", name="Bear", line={"color": "#d15b5b", "dash": "dot"})
)
fig.add_trace(
    go.Scatter(x=_x(series.base), y=_y(series.base), mode="lines", name="Base", line={"width": 3})
)

realized = realized_progress_path("pricegauger.db", forecast)
if realized:
    fig.add_trace(
        go.Scatter(
            x=[progress * horizon for progress, _ in realized],
            y=[move for _, move in realized],
            mode="lines+markers",
            name="Faktisk utvikling",
            line={"color": "#252b33", "width": 3},
            marker={"size": 5},
        )
    )

if outcome is not None and outcome.status == "PARTIAL":
    fig.add_vline(
        x=outcome.progress * horizon,
        line_dash="dash",
        annotation_text="observert hit",
        annotation_position="top",
    )

fig.add_hline(y=0.0, line_width=1, opacity=0.3)
fig.update_layout(
    height=500,
    margin={"l": 20, "r": 20, "t": 30, "b": 20},
    xaxis_title="Aktiv handelstid etter forecast (timer)",
    yaxis_title="Endring fra referansepris (%)",
    legend={"orientation": "h", "y": 1.08, "x": 0},
    hovermode="x unified",
)
st.plotly_chart(fig, use_container_width=True)

if outcome is None:
    st.info("Workeren har ennå ikke opprettet et ForecastOutcome for denne prognosen.")
else:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Outcome-status", outcome.status)
    c2.metric("Observert horisont", f"{outcome.progress:.0%}")
    c3.metric("Faktisk endring", "—" if outcome.realized_move_pct is None else f"{outcome.realized_move_pct:+.2f}%")
    c4.metric("Referansepris", "—" if outcome.reference_price is None else f"{outcome.reference_price:,.3f}")

    d1, d2, d3, d4 = st.columns(4)
    d1.metric("Retning", "—" if outcome.direction_hit is None else ("TREFF" if outcome.direction_hit else "BOM"))
    d2.metric("Intervall", "—" if outcome.interval_hit is None else ("TREFF" if outcome.interval_hit else "BOM"))
    d3.metric("MFE", "—" if outcome.mfe_pct is None else f"{outcome.mfe_pct:+.2f}%")
    d4.metric("MAE", "—" if outcome.mae_pct is None else f"{outcome.mae_pct:+.2f}%")

st.caption(
    f"Original forecast: {forecast.expected_move_low_pct:+.2f}% … {forecast.expected_move_high_pct:+.2f}% "
    f"over {forecast.horizon_hours:g}t · confidence {forecast.confidence:.0%} · {forecast.status}."
)
