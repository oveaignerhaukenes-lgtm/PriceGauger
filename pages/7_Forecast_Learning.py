from __future__ import annotations

from datetime import datetime, timedelta, timezone

import plotly.graph_objects as go
import streamlit as st

from analysis_view_preferences import ANALYSIS_ENGINES
from build_info import render_build_badge
from forecast_learning import ForecastOutcomeStore
from forecast_store import ForecastStore
from market_detail import (
    RESOLUTION_CHOICES,
    downsample_history,
    fade_path_segments,
    forecast_price_series,
    ghost_forecast_opacities,
    resolution_minutes,
)
from market_detail_controls import ENGINE_LABELS, render_market_detail_controls
from market_detail_projection import load_market_detail_projection
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
        "Grafinnstillinger ligger i sidebaren; grafen leser bare lagret worker-data."
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

market, resolution, show_learning, enabled_engines = render_market_detail_controls(
    st,
    markets=markets,
    initial_market=initial_market,
    resolution_choices=RESOLUTION_CHOICES,
)

if st.query_params.get("market") != market:
    st.query_params["market"] = market

selected_labels = [ENGINE_LABELS[engine] for engine in enabled_engines]
st.caption(
    f"**{market}** · {resolution}  |  "
    + (
        "analysevisning: " + " · ".join(selected_labels)
        if selected_labels
        else "alle analysemotorer skjult"
    )
    + ("  |  tidligere prognosespor på" if show_learning else "  |  tidligere prognosespor av")
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


def _current_metrics(item, latest_forecast, *, projected: bool = False):
    if projected or item is None:
        direction = latest_forecast.direction
        confidence = latest_forecast.confidence
        interval = (
            "—"
            if latest_forecast.expected_move_low_pct is None or latest_forecast.expected_move_high_pct is None
            else f"{latest_forecast.expected_move_low_pct:+.2f}% … {latest_forecast.expected_move_high_pct:+.2f}%"
        )
        horizon = "—" if latest_forecast.horizon_hours is None else f"{latest_forecast.horizon_hours:g}t"
        recommendation = "VISNINGSVARIANT" if projected else latest_forecast.status
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


def _render_engine_breakdown(projection, engines: tuple[str, ...]) -> None:
    components = projection.components
    if components is None:
        st.caption("Motorbidrag er ikke lagret ennå; neste worker-syklus bygger komponentvisningen.")
        return
    enabled = set(engines)
    available = set(components.available_engines)
    rows = []
    for engine in ANALYSIS_ENGINES:
        rows.append(
            {
                "Motor": ENGINE_LABELS[engine],
                "Aktiv": engine in enabled,
                "Tilgjengelig": engine in available,
                "Score": round(float(components.scores.get(engine, 0.0)), 3) if engine in available else None,
                "Autoritativ vekt": round(float(components.weights.get(engine, 0.0)), 3) if engine in available else None,
            }
        )
    st.dataframe(rows, hide_index=True, use_container_width=True)
    if projection.score is None:
        st.caption(projection.reason)
    else:
        st.caption(
            f"Valgt kombinasjon gir re-normalisert score {projection.score:+.3f} · {projection.direction.replace('_', '-')}. "
            "Dette er en visningsvariant; lagret forecast og læringshistorikk endres ikke."
        )


def _add_forecast(
    fig: go.Figure,
    forecast,
    *,
    color: str,
    strong: bool,
    name: str,
    regime: str = "",
    volatility=None,
    ghost_peak_opacity: float = 0.26,
    show_legend: bool = True,
):
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
                line={"color": "#2f9e64", "dash": "dot", "width": 1.2},
            )
        )
        fig.add_trace(
            go.Scatter(
                x=bear_x,
                y=bear_y,
                mode="lines",
                name="Bear",
                line={"color": "#d15b5b", "dash": "dot", "width": 1.2},
            )
        )

    base_x, base_y = _xy(series.base)
    if strong:
        fig.add_trace(
            go.Scatter(
                x=base_x,
                y=base_y,
                mode="lines",
                name=name,
                line={"color": color, "width": 2.6},
                opacity=1.0,
                hovertemplate=f"{name}<br>%{{x|%d.%m %H:%M}}<br>%{{y:.3f}}<extra></extra>",
            )
        )
        return

    path = tuple(zip(base_x, base_y))
    segments = fade_path_segments(path, peak_opacity=ghost_peak_opacity)
    for segment_index, (segment, opacity) in enumerate(segments):
        fig.add_trace(
            go.Scatter(
                x=[point[0] for point in segment],
                y=[point[1] for point in segment],
                mode="lines",
                name=name,
                legendgroup="historical-forecasts",
                showlegend=show_legend and segment_index == len(segments) - 1,
                line={"color": color, "width": 1.05, "dash": "dot"},
                opacity=opacity,
                hoverinfo="skip",
            )
        )


def _render_market_detail(market_name: str, resolution_choice: str, learning: bool, engines: tuple[str, ...]) -> None:
    market_forecasts = forecast_store.load_all(market=market_name, limit=500)
    if not market_forecasts:
        st.info("Ingen forecasts for dette markedet ennå.")
        return

    latest = market_forecasts[0]
    item = _market_item(market_name)
    projection = load_market_detail_projection(market_name, engines)
    display_forecast = projection.forecast or latest
    is_projected = projection.forecast is not None
    _current_metrics(item, display_forecast, projected=is_projected)
    _render_engine_breakdown(projection, engines)

    horizon_hours = max(0.5, float(display_forecast.horizon_hours or 4.0))
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
                line={"color": "#252b33", "width": 2.3},
                hovertemplate="Faktisk<br>%{x|%d.%m %H:%M}<br>%{y:.3f}<extra></extra>",
            )
        )

    color = asset_color(market_name)
    regime = "" if item is None else item.market_regime
    volatility = None if item is None else item.volatility_score

    if learning:
        historical = [
            forecast
            for forecast in market_forecasts[1:30]
            if _parse_stamp(forecast.as_of) >= start - timedelta(hours=window_hours)
        ]
        visible_historical = list(reversed(historical[:8]))
        ghost_opacities = ghost_forecast_opacities(len(visible_historical))
        for index, (forecast, opacity) in enumerate(zip(visible_historical, ghost_opacities)):
            _add_forecast(
                fig,
                forecast,
                color=color,
                strong=False,
                name="Tidligere prognoser",
                ghost_peak_opacity=opacity,
                show_legend=index == len(visible_historical) - 1,
            )

    _add_forecast(
        fig,
        display_forecast,
        color=color,
        strong=True,
        name="Valgt motor-kombinasjon" if is_projected else "Gjeldende base",
        regime=regime,
        volatility=volatility,
    )

    fig.add_vline(
        x=now,
        line_width=1.2,
        line_dash="dash",
        line_color="#64748b",
        annotation_text="NÅ",
        annotation_position="top",
    )
    fig.update_xaxes(
        range=[start, end],
        title_text="Tid · nåtid holdes i sentrum",
        showgrid=True,
        showspikes=True,
        spikemode="across+toaxis",
        spikesnap="cursor",
        spikedash="dot",
        spikecolor="rgba(71,85,105,0.48)",
        spikethickness=1,
    )
    fig.update_yaxes(
        title_text=f"{market_name} · pris",
        side="right",
        showgrid=True,
        zeroline=False,
        showspikes=True,
        spikemode="across+toaxis",
        spikesnap="cursor",
        spikedash="dot",
        spikecolor="rgba(71,85,105,0.48)",
        spikethickness=1,
        hoverformat=".4~g",
    )
    fig.update_layout(
        template="plotly_white",
        height=650,
        margin={"l": 42, "r": 88, "t": 52, "b": 40},
        legend={"orientation": "h", "y": 1.04, "x": 0},
        hovermode="closest",
        dragmode="pan",
        uirevision=f"Markedsvisning:{market_name}:{resolution_choice}:{learning}",
    )
    st.plotly_chart(
        fig,
        use_container_width=True,
        config={
            "scrollZoom": True,
            "displaylogo": False,
            "modeBarButtonsToRemove": ["lasso2d", "select2d"],
        },
        key=f"market-detail-{market_name}-{resolution_choice}-{learning}-{'-'.join(engines) or 'none'}",
    )

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
        st.caption("Historiske prognosespor er skjult. Slå dem på i sidebaren for å se forecast-historikken.")
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
    _fragment(run_every="60s")(_render_market_detail)(market, resolution, show_learning, enabled_engines)
else:
    _render_market_detail(market, resolution, show_learning, enabled_engines)
