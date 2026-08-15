from __future__ import annotations

import html
from dataclasses import dataclass
from typing import Mapping

from overview_v2_read_model import OverviewTechnicalV2, load_v2_overview_snapshots
from runtime_health_v2 import RuntimeHealthV2, freshness_health_v2, load_runtime_health_v2
from v2_forecast_visualization import V2_FORECAST_CSS, render_v2_forecast_chart, render_v2_technical_explanation


_HORIZON_PREFIX = "overview_v2_horizon:"
_INTERPRETER_PREFIX = "overview_v2_interpreter:"


@dataclass(frozen=True, slots=True)
class OverviewV2Health:
    status: str
    detail: str


def _horizon_label(seconds: int) -> str:
    value = int(seconds)
    if value < 3600:
        return f"{value // 60:g}m"
    hours = value / 3600.0
    if abs(hours - 168.0) <= 1e-6:
        return "7d"
    return f"{hours:g}t"


def _direction_label(direction: str) -> str:
    return {
        "BULLISH": "BULLISH",
        "BEARISH": "BEARISH",
        "NEUTRAL": "NØYTRAL",
    }.get(str(direction).upper(), str(direction).replace("_", " "))


def _action_label(direction: str) -> str:
    return {
        "BULLISH": "LONG-BIAS",
        "BEARISH": "SHORT-BIAS",
        "NEUTRAL": "AVVENT",
    }.get(str(direction).upper(), "AVVENT")


def _price_interval(view: OverviewTechnicalV2) -> str:
    if not view.price_history:
        return "Ikke tilgjengelig"
    reference = float(view.price_history[-1][1])
    low = reference * (1.0 + float(view.lower_return))
    high = reference * (1.0 + float(view.upper_return))
    decimals = 3 if abs(reference) < 100 else 2
    return f"{low:.{decimals}f} til {high:.{decimals}f}"


def _health_for_view(
    view: OverviewTechnicalV2,
    persisted: RuntimeHealthV2 | None,
) -> OverviewV2Health:
    freshness = freshness_health_v2(
        service="v2-technical-runtime",
        stage=view.market,
        observed_at=view.as_of,
    )
    parts = [freshness.detail]
    status = freshness.status
    if persisted is not None:
        parts.append(f"runtime {persisted.status}")
        if persisted.status in {"DEGRADED", "NO_DATA"}:
            status = persisted.status
        elif persisted.status == "STALE" and status == "HEALTHY":
            status = "STALE"
    return OverviewV2Health(status=status, detail=" · ".join(parts))


def render_overview_v2_market_card_html(
    view: OverviewTechnicalV2,
    *,
    health: OverviewV2Health,
    color: str,
    detail_href: str,
) -> str:
    expected = f"{float(view.expected_return) * 100:+.3f}%"
    interval = f"{float(view.lower_return) * 100:+.3f}% til {float(view.upper_return) * 100:+.3f}%"
    chart = render_v2_forecast_chart(view)
    explanation = render_v2_technical_explanation(view)
    health_class = " pg-v2-health-warning" if health.status != "HEALTHY" else ""
    layer_note = " + Interpreter" if view.applied_layers else ""
    return "".join(
        line.strip()
        for line in f"""
        <article class="pg-market-card pg-market-card-v2" style="--market-color:{html.escape(color, quote=True)}">
          <div class="pg-market-layout pg-market-layout-v2">
            <section class="pg-analysis pg-analysis-v2">
              <div class="pg-state-top">
                <div class="pg-market"><a class="pg-market-title-link" href="{html.escape(detail_href, quote=True)}" target="_self">{html.escape(view.market)}</a></div>
                <div class="pg-direction">{html.escape(_direction_label(view.direction))}</div>
              </div>
              {explanation}
              <div class="pg-data-health{health_class}"><strong>{html.escape(health.status)}</strong> · {html.escape(health.detail)}</div>
            </section>
            <aside class="pg-recommendation pg-recommendation-v2">
              <div class="pg-rec-kicker">TEKNISK PROGNOSE</div>
              <div class="pg-rec-action">{html.escape(_action_label(view.direction))}</div>
              <div class="pg-rec-signal">{html.escape(view.recipe_label + layer_note)}</div>
              <div class="pg-rec-grid">
                <div class="pg-rec-row"><strong>{html.escape(expected)}</strong>forventet terminal move</div>
                <div class="pg-rec-row"><strong>{html.escape(interval)}</strong>uncertainty-intervall</div>
                <div class="pg-rec-row"><strong>{html.escape(_price_interval(view))}</strong>implisert prisintervall</div>
                <div class="pg-rec-row"><strong>{html.escape(_horizon_label(view.horizon_seconds))}</strong>valgt prognosehorisont</div>
                <div class="pg-rec-row"><strong>{float(view.confidence):.0%}</strong>Technical Core confidence</div>
              </div>
              <div class="pg-rec-status">V2 · {html.escape(view.path_shape.replace("_", " "))}</div>
            </aside>
            <section class="pg-forecast pg-forecast-v2">{chart}</section>
          </div>
        </article>
        """.splitlines()
    )


OVERVIEW_V2_CSS = V2_FORECAST_CSS + """
<style>
.pg-market-layout-v2{grid-template-columns:minmax(18rem,4fr) minmax(12rem,1.65fr) minmax(20rem,4.2fr)!important}
.pg-analysis-v2 .pg-v2-explain{border:0;background:transparent;padding:.55rem 0 0}
.pg-analysis-v2 .pg-v2-recipe{margin-bottom:.45rem}
.pg-forecast-v2 .pg-v2-chart{border:0;background:transparent;padding:0;height:100%}
.pg-forecast-v2 .pg-v2-chart svg{height:9.4rem}
.pg-v2-overview-controls{margin:.15rem 0 .3rem}
.pg-v2-health-warning{font-weight:650}
@media(max-width:1100px){.pg-market-layout-v2{grid-template-columns:minmax(0,3fr) minmax(13rem,1.4fr)!important}.pg-forecast-v2{grid-column:1 / -1}.pg-forecast-v2 .pg-v2-chart svg{height:8.5rem}}
@media(max-width:700px){.pg-market-layout-v2{grid-template-columns:1fr!important}.pg-forecast-v2{grid-column:auto}.pg-forecast-v2 .pg-v2-chart svg{height:8rem}}
</style>
"""


def render_v2_overview_market_cards(st, *, asset_color, market_detail_href) -> None:
    """Render Overview's active market forecast surface from persisted v2 only.

    The first read discovers coherent persisted workspaces and available horizons.
    Widget changes are then applied through a second read/composition pass. Neither
    pass invokes Technical Core, an interpreter provider, Saxo, or persistence.
    """
    st.markdown(OVERVIEW_V2_CSS, unsafe_allow_html=True)
    try:
        baselines = load_v2_overview_snapshots()
    except Exception as exc:
        st.warning(f"Kunne ikke lese v2-markedsprognoser: {exc}")
        return

    if not baselines:
        st.info("Venter på persisterte TA-only v2 workspaces. Gammel analysegeometri brukes ikke som skjult fallback.")
        return

    selected_horizons: dict[str, int] = {}
    interpreter_by_market: dict[str, bool] = {}
    placeholders: dict[str, object] = {}

    for market, baseline in baselines.items():
        with st.container():
            control_a, control_b, control_c = st.columns([1.0, 3.2, 1.8])
            with control_a:
                st.checkbox("Technicals", value=True, disabled=True, key=f"overview-v2-technicals:{market}")
            with control_b:
                selected = st.segmented_control(
                    f"Prognosehorisont · {market}",
                    options=baseline.available_horizons,
                    default=baseline.horizon_seconds,
                    format_func=_horizon_label,
                    key=f"{_HORIZON_PREFIX}{market}",
                    label_visibility="collapsed",
                )
                selected_horizons[market] = int(selected if selected is not None else baseline.horizon_seconds)
            with control_c:
                enabled = st.checkbox(
                    "Technical Interpreter",
                    value=False,
                    disabled=not baseline.interpreter_available,
                    help=(
                        "Komponerer fingerprint-matchet cached output; ingen AI-kall fra Overview."
                        if baseline.interpreter_available
                        else "Ingen kompatibel cached Interpreter-output for dette workspace-snapshotet."
                    ),
                    key=f"{_INTERPRETER_PREFIX}{market}",
                )
                interpreter_by_market[market] = bool(enabled)
            placeholders[market] = st.empty()

    try:
        views = load_v2_overview_snapshots(
            requested_horizons=selected_horizons,
            interpreter_by_market=interpreter_by_market,
        )
    except Exception as exc:
        st.warning(f"Kunne ikke komponere valgte v2-visninger: {exc}")
        return

    try:
        persisted_health = {
            item.stage: item for item in load_runtime_health_v2(service="v2-technical-runtime")
        }
    except Exception:
        persisted_health = {}

    for market, placeholder in placeholders.items():
        view = views.get(market)
        if view is None:
            placeholder.warning(f"{market}: v2-workspace mangler for valgt horisont.")
            continue
        health = _health_for_view(view, persisted_health.get(market))
        placeholder.markdown(
            render_overview_v2_market_card_html(
                view,
                health=health,
                color=asset_color(market),
                detail_href=market_detail_href(market),
            ),
            unsafe_allow_html=True,
        )

    st.caption(
        "Markedskortene leser persistert v2 Technical Core/workspace. Horisont- og layerbytte er read-only composition av lagrede/cached outputs; ingen analyse, AI-provider eller Saxo-kall kjøres fra Overview."
    )
