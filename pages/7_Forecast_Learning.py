from __future__ import annotations

from datetime import datetime, timedelta, timezone

import plotly.graph_objects as go
import streamlit as st

from build_info import render_build_badge
from forecast_learning import ForecastOutcomeStore
from forecast_store import ForecastStore
from market_detail import RESOLUTION_CHOICES, downsample_history, forecast_price_series, resolution_minutes
from market_history_store import MarketHistoryStore
from overview_service import load_overview
from overview_visuals import asset_color


st.set_page_config(page_title="Markedsvisning · PriceGauger", page_icon="📈", layout="wide")
render_build_badge()

header_left, header_right = st.columns([5, 1])
with header_left:
    st.title("Markedsvisning")
    st.caption(
        "Levende markedsbilde med frosne forecasts og faktisk utvikling. "
        "Grafen leser bare lagret worker-data; den sender ingen markedsdata- eller ordreforespørsler."
    )
with header_right:
    st.page_link("pages/0_Oversikt.py", label="Til Oversikt", icon="📡")

forecast_store = ForecastStore()
outcome_store = ForecastOutcomeStore()
all_forecasts = forecast_store.load_all(limit=2000)

if not all_forecasts:
    st.info("Ingen ForecastSnapshots er lagret ennå.")
    st.stop()

markets = sorted({item.market for item in all_forecasts})
requested = st.query_params.get("market")
if isinstance(requested, list):
    requested = requested[0] if requested else None
requested = str(requested) if requested else None
initial_market = requested if requested in markets else markets[0]

control_market, control_resolution, control_learning = st.columns([2.2, 3.2, 2.2])
with control_market:
    market = st.selectbox("Marked", markets, index=markets.index(initial_market))
with control_resolution:
    resolution = st.radio("Tidsoppløsning", RESOLUTION_CHOICES, horizontal=True, index=0)
with control_learning:
    show_learning = st.toggle("Vis læring / gamle forecasts", value=True)

if st.query_params.get("market") != market:
    st.query_params["market"] = market

st.caption(
    "AUTO velger visningsoppløsning etter forecast-horisonten. Valgt oppløsning kan ikke bli finere "
    "enn markedsdata som faktisk er lagret av workeren."
)


def _parse_stamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _xy(points):
    return ([_parse_stamp(stamp) for stamp, _ in points], [float(value) for _, value in points])


def _market_item(market_name: str):
    try:
        data = load_overview()
    except Exception:
        return None
    return next((item for item in data.markets if item.market == market_name), None)


def _current_metrics(item, latest_forecast):
    if item is None:
        direction = latest_forecast.direction
        confidence = latest_forecast.confidence
        interval = (
            "—"
            if latest_forecast.expected_move_low_pct is None or latest_forecast.expected_move_high_pct is None
            else f"{latest_forecast.expected_move_low_pct:+.2f}% … {latest_forecast.expected_move_high_pct:+.2f}%"
        )
        horizon = "—" if latest_forecast.horizon_hours is None else f"{latest_forecast.horizon_hours:g}t"
        recommendation = latest_forecast.status
    else:
        direction = item.direction
        confidence = item.confidence
        interval = (
            "—"
            if item.expected_move_low_pct is None or item.expected_move_high_pct is None
            else f"{item.expected_move_low_pct:+.2f}% … {item.expected_move_high_pct:+.2f}%"
        )
        horizon = "—" if item.horizon_hours is None else f"{item.horizon_hours:g}t"
        recommendation = item.recommendation_status

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Retning", direction.replace("_", "-"))
    m2.metric("Konfidens", f"{confidence:.0%}")
    m3.metric("Forventet intervall", interval)
    m4.metric("Horisont", horizon)
    m5.metric("Status", recommendation)



def _add_forecast(fig: go.Figure, forecast, *, color: str, strong: bool, name: str, regime: str = "", volatility=None):
    series = forecast_price_series(
        forecast,
        market_regime=regime,
        volatility_score=volatility,
        steps=30,
    )
    if not series.base:
        return

    if strong:
        lower_x, lower_y = _xy(series.fan_lower)
        upper_x, upper_y = _xy(series.fan_upper)
        fig.add_trace(
            go.Scatter(
                x=lower_x,
                y=lower_y,
                mode="lines",
                line={"width": 0},
                hoverinfo="skip",
                showlegend=False,
                name="Nedre usikkerhet",
            )
        )
        fig.add_trace(
            go.Scatter(
                x=upper_x,
                y=upper_y,
                mode="lines",
                line={"width": 0},
                fill="tonexty",
                fillcolor="rgba(120,144,179,0.16)",
                hoverinfo="skip",
                name="Usikkerhetsfelt",
            )
        )
        bull_x, bull_y = _xy(series.bull)
        bear_x, bear_y = _xy(series.bear)
        fig.add_trace(
            go.Scatter(
                x=bull_x,
                y=bull_y,
                mode="lines",
                name="Bull",
                line={"color": "#2f9e64", "dash": "dot", "width": 1.4},
            )
        )
        fig.add_trace(
            go.Scatter(
                x=bear_x,
                y=bear_y,
                mode="lines",
                name="Bear",
                line={"color": "#d15b5b", "dash": "dot", "width": 1.4},
            )
        )

    base_x, base_y = _xy(series.base)
    fig.add_trace(
        go.Scatter(
            x=base_x,
            y=base_y,
            mode="lines",
            name=name,
            line={"color": color, "width": 3.0 if strong else 1.2, "dash": "solid" if strong else "dot"},
            opacity=1.0 if strong else 0.26,
            hovertemplate=(
                f"{name}<br>%{{x|%d.%m %H:%M}}<br>%{{y:.3f}}<extra></extra>"
            ),
        )
    )



def _render_market_detail(market_name: str, resolution_choice: str, learning: bool) -> None:
    market_forecasts = forecast_store.load_all(market=market_name, limit=500)
    if not market_forecasts:
        st.info("Ingen forecasts for dette markedet ennå.")
        return

    latest = market_forecasts[0]
    item = _market_item(market_name)
    _current_metrics(item, latest)

    horizon_hours = max(0.5, float(latest.horizon_hours or 4.0))
    window_hours = max(1.0, min(48.0, horizon_hours))
    now = datetime.now(timezone.utc)
    start = now - timedelta(hours=window_hours)
    end = now + timedelta(hours=window_hours)
    minutes = resolution_minutes(resolution_choice, horizon_hours=horizon_hours)

    raw_history = MarketHistoryStore().load_range(
        market=market_name,
        start=start,
        end=now,
        limit=10000,
    )
    history = downsample_history(raw_history, minutes=minutes)

    fig = go.Figure()
    if history:
        history_x, history_y = _xy(history)
        fig.add_trace(
            go.Scatter(
                x=history_x,
                y=history_y,
                mode="lines",
                name="Faktisk pris",
                line={"color": "#252b33", "width": 2.7},
                hovertemplate="Faktisk<br>%{x|%d.%m %H:%M}<br>%{y:.3f}<extra></extra>",
            )
        )

    color = asset_color(market_name)
    regime = "" if item is None else item.market_regime
    volatility = None if item is None else item.volatility_score

    if learning:
        historical = [forecast for forecast in market_forecasts[1:30] if _parse_stamp(forecast.as_of) >= start - timedelta(hours=window_hours)]
        for index, forecast in enumerate(reversed(historical[-8:])):
            label = f"Tidligere forecast {index + 1}" if index == 0 else f"_ghost_{index}"
            _add_forecast(
                fig,
                forecast,
                color=color,
                strong=False,
                name=label,
            )

    _add_forecast(
        fig,
        latest,
        color=color,
        strong=True,
        name="Gjeldende base",
        regime=regime,
        volatility=volatility,
    )

    fig.add_vline(
        x=now,
        line_width=1.5,
        line_dash="dash",
        line_color="#64748b",
        annotation_text="NÅ",
        annotation_position="top",
    )
    fig.update_xaxes(range=[start, end])
    fig.update_layout(
        height=620,
        margin={"l": 20, "r": 20, "t": 40, "b": 20},
        xaxis_title="Tid · nåtid holdes i sentrum",
        yaxis_title="Pris",
        legend={"orientation": "h", "y": 1.08, "x": 0},
        hovermode="x unified",
    )
    st.plotly_chart(fig, use_container_width=True, key=f"market-detail-{market_name}-{resolution_choice}-{learning}")

    if not history:
        st.caption(
            "Ingen lagrede markedsobservasjoner ligger i det synlige klokkevinduet. "
            "Det er normalt når markedet er stengt; forsiden beholder siste aktive handelshistorikk."
        )
    else:
        st.caption(
            f"Faktisk pris: {len(history)} lagrede punkter · visning {resolution_choice} "
            f"({minutes} min bucket). Grafen oppdateres fra worker-data, ikke direkte fra Saxo i nettleseren."
        )

    outcomes = outcome_store.load_all(market=market_name, limit=500)
    completed = [outcome for outcome in outcomes if outcome.status == "COMPLETE"]
    direction_scored = [outcome for outcome in completed if outcome.direction_hit is not None]
    interval_scored = [outcome for outcome in completed if outcome.interval_hit is not None]
    latest_outcome = next((outcome for outcome in outcomes if outcome.forecast_id == latest.forecast_id), None)

    st.subheader("Læring", divider="gray")
    l1, l2, l3, l4 = st.columns(4)
    l1.metric("Fullførte forecasts", len(completed))
    l2.metric(
        "Retningstreff",
        "—" if not direction_scored else f"{100 * sum(bool(outcome.direction_hit) for outcome in direction_scored) / len(direction_scored):.0f}%",
    )
    l3.metric(
        "Innenfor intervall",
        "—" if not interval_scored else f"{100 * sum(bool(outcome.interval_hit) for outcome in interval_scored) / len(interval_scored):.0f}%",
    )
    l4.metric(
        "Gjeldende forecast observert",
        "—" if latest_outcome is None else f"{latest_outcome.progress:.0%}",
    )

    if not learning:
        st.caption("Historiske forecast-baner er skjult. Slå på «Vis læring / gamle forecasts» for overlay.")
    elif completed:
        recent = completed[:8]
        rows = []
        for outcome in recent:
            rows.append(
                {
                    "forecast": _parse_stamp(outcome.forecast_as_of).strftime("%d.%m %H:%M"),
                    "retning": "—" if outcome.direction_hit is None else ("treff" if outcome.direction_hit else "bom"),
                    "intervall": "—" if outcome.interval_hit is None else ("treff" if outcome.interval_hit else "bom"),
                    "utfall": None if outcome.realized_move_pct is None else round(outcome.realized_move_pct, 3),
                    "MFE": None if outcome.mfe_pct is None else round(outcome.mfe_pct, 3),
                    "MAE": None if outcome.mae_pct is None else round(outcome.mae_pct, 3),
                }
            )
        st.dataframe(rows, use_container_width=True, hide_index=True)


_fragment = getattr(st, "fragment", getattr(st, "experimental_fragment", None))
if _fragment is not None:
    _fragment(run_every="60s")(_render_market_detail)(market, resolution, show_learning)
else:
    _render_market_detail(market, resolution, show_learning)
