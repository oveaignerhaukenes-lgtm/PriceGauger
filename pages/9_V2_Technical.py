from __future__ import annotations

import streamlit as st

from build_info import render_build_badge
from overview_v2_read_model import load_v2_overview_snapshots
from runtime_health_v2 import load_runtime_health_v2


st.set_page_config(page_title="V2 Technical · PriceGauger", page_icon="📈", layout="wide")
render_build_badge()

st.title("V2 Technical")
st.caption(
    "Read-only visning av den nye Technical Core-basen. Siden leser kun persistert v2-state; "
    "den utløser ikke analyse, AI-kall, Saxo-kall eller handler."
)

show_interpreter = st.checkbox("Vis Technical Interpreter", value=True)

try:
    snapshots = load_v2_overview_snapshots()
except Exception as exc:
    st.warning(f"V2-data er ikke tilgjengelig ennå: {exc}")
    snapshots = {}

if not snapshots:
    st.info("Venter på første persisterte TA-only v1 workspace i DB v2.")
else:
    market = st.selectbox("Marked", options=sorted(snapshots))
    view = snapshots[market]

    cols = st.columns(5)
    cols[0].metric("Retning", view.direction)
    cols[1].metric("Forventet move", f"{view.expected_return * 100:+.3f}%")
    cols[2].metric("Konfidens", f"{view.confidence:.0%}")
    cols[3].metric("Horisont", f"{view.horizon_seconds // 60:g} min")
    cols[4].metric("Path", view.path_shape)

    st.caption(f"Snapshot: {view.as_of}")
    st.write(
        {
            "trend": view.trend_state,
            "momentum": view.momentum_state,
            "structure": view.structure_state,
            "interval": {
                "low_pct": round(view.lower_return * 100, 4),
                "expected_pct": round(view.expected_return * 100, 4),
                "high_pct": round(view.upper_return * 100, 4),
            },
        }
    )

    if show_interpreter:
        st.subheader("Technical Interpreter")
        if view.interpreter_summary:
            confidence = "ukjent" if view.interpreter_confidence is None else f"{view.interpreter_confidence:.0%}"
            st.write(view.interpreter_summary)
            st.caption(f"Interpreter-konfidens: {confidence}")
        else:
            st.info("Ingen kompatibel cached Technical Interpreter-output finnes for dette workspace-snapshotet.")

st.divider()
st.subheader("V2 runtime health")
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
