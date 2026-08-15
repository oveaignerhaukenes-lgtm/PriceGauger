from __future__ import annotations

import streamlit as st

from build_info import render_build_badge
from overview_v2_read_model import load_v2_overview_snapshots
from runtime_health_v2 import freshness_health_v2, load_runtime_health_v2
from v2_forecast_visualization import (
    V2_FORECAST_CSS,
    render_v2_forecast_chart,
    render_v2_technical_explanation,
)


st.set_page_config(page_title="V2 Technical · PriceGauger", page_icon="📈", layout="wide")
render_build_badge()

st.title("V2 Technical")
st.caption(
    "Read-only inspeksjon av den persisterte v2 Technical Core-basen og eventuelle cached refinement-lag. "
    "Lagbytte komponerer eksisterende workspace-output; det utløser ikke ny analyse eller providerarbeid."
)
st.markdown(V2_FORECAST_CSS, unsafe_allow_html=True)


def _horizon_label(seconds: int) -> str:
    value = int(seconds)
    if value < 3600:
        return f"{value // 60:g}m"
    hours = value / 3600.0
    return f"{hours:g}t"


def _render_inspector() -> None:
    try:
        baseline_views = load_v2_overview_snapshots()
    except Exception as exc:
        st.warning(f"V2-data er ikke tilgjengelig ennå: {exc}")
        return

    if not baseline_views:
        st.info("Venter på første persisterte TA-only v1 workspace i DB v2.")
        return

    market = st.selectbox("Marked", options=sorted(baseline_views), key="v2-tech-market")
    baseline = baseline_views[market]
    horizons = baseline.available_horizons
    selected_horizon = st.segmented_control(
        "Prognosehorisont",
        options=horizons,
        default=baseline.horizon_seconds if baseline.horizon_seconds in horizons else horizons[0],
        format_func=_horizon_label,
        key=f"v2-tech-horizon:{market}",
    )
    if selected_horizon is None:
        selected_horizon = baseline.horizon_seconds

    layer_col, interpreter_col = st.columns([1, 2])
    with layer_col:
        st.checkbox("Technicals", value=True, disabled=True, key=f"v2-technicals:{market}")
    with interpreter_col:
        use_interpreter = st.checkbox(
            "Technical Interpreter",
            value=False,
            disabled=not baseline.interpreter_available,
            help=(
                "Bruker kun fingerprint-matchet cached output fra dette workspace-snapshotet."
                if baseline.interpreter_available
                else "Ingen kompatibel cached Technical Interpreter-output finnes for dette snapshotet ennå."
            ),
            key=f"v2-interpreter:{market}",
        )

    try:
        views = load_v2_overview_snapshots(
            requested_horizons={market: int(selected_horizon)},
            interpreter_by_market={market: bool(use_interpreter)},
        )
        view = views[market]
    except Exception as exc:
        st.warning(f"Kunne ikke komponere valgt v2-visning: {exc}")
        return

    freshness = freshness_health_v2(
        service="v2-technical-runtime",
        stage=market,
        observed_at=view.as_of,
    )
    persisted_health = None
    try:
        persisted_health = next(
            (item for item in load_runtime_health_v2(service="v2-technical-runtime") if item.stage == market),
            None,
        )
    except Exception:
        persisted_health = None

    health_detail = freshness.detail
    if persisted_health is not None and persisted_health.detail:
        health_detail += f" · runtime: {persisted_health.status}"
    st.caption(
        f"{view.recipe_label} · snapshot {view.as_of} · freshness {freshness.status} · {health_detail}"
    )

    chart = render_v2_forecast_chart(view)
    explanation = render_v2_technical_explanation(view)
    st.markdown(
        f'<div class="pg-v2-layout">{chart}{explanation}</div>',
        unsafe_allow_html=True,
    )

    cols = st.columns(4)
    cols[0].metric("Retning", view.direction)
    cols[1].metric("Forventet move", f"{view.expected_return * 100:+.3f}%")
    cols[2].metric("TA confidence", f"{view.confidence:.0%}")
    cols[3].metric("Horisont", _horizon_label(view.horizon_seconds))

    if not baseline.interpreter_available:
        st.caption(
            "Technical Interpreter er foreløpig ikke en del av live TA-runtime. Toggle blir aktiv automatisk når et kompatibelt cached layer-output finnes."
        )


_fragment = getattr(st, "fragment", getattr(st, "experimental_fragment", None))
if _fragment is not None:
    _fragment(run_every="15s")(_render_inspector)()
else:
    _render_inspector()

with st.expander("V2 runtime health"):
    try:
        health = load_runtime_health_v2()
    except Exception as exc:
        st.caption(f"Runtime health kunne ikke leses: {exc}")
    else:
        if not health:
            st.caption("Ingen v2 runtime health er registrert ennå.")
        else:
            st.dataframe(
                [
                    {
                        "service": item.service,
                        "stage": item.stage,
                        "status": item.status,
                        "detail": item.detail,
                    }
                    for item in health
                ],
                use_container_width=True,
                hide_index=True,
            )
