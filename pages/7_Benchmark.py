from __future__ import annotations

import streamlit as st

from build_info import render_build_badge
from manual_mix_preview_v2 import blend_manual_mix_preview_v2, load_latest_mix_basis_v2
from parallel_forecast_benchmark_read_model_v2 import load_benchmark_aggregates_v2


st.set_page_config(page_title="Benchmark · PriceGauger", page_icon="🧪", layout="wide")
render_build_badge()

st.title("Technical vs Context benchmark")
st.caption(
    "Read-only sammenligning av TECH_ONLY og den faste TECH+CONTEXT-kandidaten mot samme realiserte markedsutfall. "
    "Ingen læring eller vekting skjer her."
)

try:
    aggregates = load_benchmark_aggregates_v2()
except Exception as exc:
    st.warning(f"Benchmark-data er ikke tilgjengelig ennå: {exc}")
    aggregates = ()

if aggregates:
    markets = sorted({item.market for item in aggregates})
    horizons = sorted({item.horizon_seconds for item in aggregates})
    c1, c2 = st.columns(2)
    market_filter = c1.selectbox("Marked", ["Alle", *markets])
    horizon_filter = c2.selectbox(
        "Horisont",
        ["Alle", *horizons],
        format_func=lambda value: "Alle" if value == "Alle" else f"{int(value) // 60} min",
    )
    selected = [
        item
        for item in aggregates
        if (market_filter == "Alle" or item.market == market_filter)
        and (horizon_filter == "Alle" or item.horizon_seconds == int(horizon_filter))
    ]

    rows = []
    for item in selected:
        rows.append(
            {
                "Marked": item.market,
                "Horisont": f"{item.horizon_seconds // 60} min",
                "n": item.sample_size,
                "TA MAE": round(item.technical_mae, 6),
                "TA+Context MAE": round(item.technical_context_mae, 6),
                "Δ MAE": round(item.mae_delta, 6),
                "TA retning": f"{item.technical_direction_hit_rate:.1%}",
                "TA+Context retning": f"{item.technical_context_direction_hit_rate:.1%}",
                "Δ retning": f"{item.direction_hit_rate_delta:+.1%}",
                "Context W/T/L": f"{item.context_wins}/{item.ties}/{item.context_losses}",
            }
        )
    st.dataframe(rows, hide_index=True, use_container_width=True)
    st.caption("Negativ Δ MAE betyr at Context-kandidaten har lavere gjennomsnittlig absolutt feil. Små utvalg må tolkes som små utvalg.")
else:
    st.info("Ingen fullt parede, modnede benchmark-observasjoner ennå.")

st.divider()
st.subheader("Blind manual mix-preview")
st.caption(
    "Dette interpolerer kun mellom TECH_ONLY og den allerede produserte faste TECH+CONTEXT-kandidaten. "
    "Previewen lagres ikke, trener ingenting og endrer ikke canonical forecast."
)

try:
    latest = load_latest_mix_basis_v2()
except Exception as exc:
    st.warning(f"Ingen preview-basis tilgjengelig: {exc}")
    latest = None

if latest is None:
    st.info("Ingen parallelle forecast-eksperimenter er tilgjengelige ennå.")
else:
    mix_percent = st.slider(
        "Mix",
        min_value=0,
        max_value=100,
        value=50,
        step=1,
        help="0 % = TECH_ONLY. 100 % = dagens faste TECH+CONTEXT-kandidat.",
    )
    preview = blend_manual_mix_preview_v2(latest, mix_fraction=mix_percent / 100.0)
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("TECH_ONLY", f"{preview.technical_return:+.3%}")
    m2.metric("TECH+CONTEXT", f"{preview.technical_context_return:+.3%}")
    m3.metric("Manual preview", f"{preview.preview_return:+.3%}")
    m4.metric("Retning", preview.direction)
    st.caption(
        f"{preview.market} · {preview.horizon_seconds // 60} min · as-of {preview.forecast_as_of} · "
        f"preview-intervall {preview.preview_lower_return:+.3%} … {preview.preview_upper_return:+.3%}"
    )
    st.info("Læring: AV. Denne kontrollen er kun et menneskelig inspeksjonsverktøy i AP11.")
