from __future__ import annotations

import html

import streamlit as st

from build_info import render_build_badge
from world_state import WorldState, fetch_world_state


st.set_page_config(page_title="World State", page_icon="🌍", layout="wide")
render_build_badge()

st.markdown(
    """
    <style>
    .ws-summary {
        display:grid;
        grid-template-columns:repeat(4,minmax(0,1fr));
        gap:.8rem;
        margin:.35rem 0 1rem;
    }
    .ws-stat {
        padding:.7rem .8rem;
        border:1px solid rgba(128,128,128,.22);
        border-radius:.55rem;
        background:rgba(128,128,128,.035);
    }
    .ws-label { color:rgba(128,128,128,.95); font-size:.76rem; margin-bottom:.22rem; }
    .ws-value { font-size:1rem; font-weight:650; line-height:1.2; overflow-wrap:anywhere; }
    .ws-row {
        display:grid;
        grid-template-columns:minmax(10rem,1.4fr) minmax(9rem,3fr) 3.2rem 4.8rem;
        gap:.65rem;
        align-items:center;
        padding:.42rem 0;
        border-bottom:1px solid rgba(128,128,128,.13);
    }
    .ws-name { font-size:.9rem; }
    .ws-track { height:.62rem; border-radius:999px; background:rgba(128,128,128,.2); overflow:hidden; }
    .ws-fill { height:100%; border-radius:999px; background:#ff4b4b; }
    .ws-score { text-align:right; font-variant-numeric:tabular-nums; font-weight:650; }
    .ws-change { text-align:right; font-variant-numeric:tabular-nums; font-size:.82rem; }
    .ws-assets {
        display:grid;
        grid-template-columns:repeat(4,minmax(0,1fr));
        gap:.7rem;
        margin-top:.5rem;
    }
    .ws-asset { padding:.65rem .7rem; border-left:3px solid #ff4b4b; background:rgba(128,128,128,.055); }
    .ws-asset-name { color:rgba(128,128,128,.95); font-size:.75rem; }
    .ws-asset-bias { font-weight:650; margin-top:.15rem; }
    .ws-asset-score { font-size:.8rem; margin-top:.15rem; }
    @media(max-width:850px) {
        .ws-summary,.ws-assets { grid-template-columns:repeat(2,minmax(0,1fr)); }
    }
    @media(max-width:600px) {
        .ws-row { grid-template-columns:1fr 3rem 4rem; gap:.5rem; }
        .ws-track { grid-column:1 / -1; grid-row:2; }
        .ws-summary,.ws-assets { grid-template-columns:1fr 1fr; }
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def _change_label(value: int) -> str:
    if value > 0:
        return f"↑ +{value}"
    if value < 0:
        return f"↓ {value}"
    return "→ 0"


def render_world_state(state: WorldState) -> None:
    summary = [
        ("World mood", state.mood_label),
        ("Mood score", f"{state.mood_score} / 100"),
        ("Direction", state.direction),
        ("Confidence", f"{state.confidence} %"),
    ]
    cards = "".join(
        f'<div class="ws-stat"><div class="ws-label">{html.escape(label)}</div>'
        f'<div class="ws-value">{html.escape(value)}</div></div>'
        for label, value in summary
    )
    st.markdown(f'<div class="ws-summary">{cards}</div>', unsafe_allow_html=True)

    st.markdown("### Global state profile")
    rows = "".join(
        f"""
        <div class="ws-row">
          <div class="ws-name">{html.escape(item.name)}</div>
          <div class="ws-track"><div class="ws-fill" style="width:{item.score}%"></div></div>
          <div class="ws-score">{item.score}</div>
          <div class="ws-change">{html.escape(_change_label(item.change))}</div>
        </div>
        """
        for item in state.categories
    )
    st.markdown(rows, unsafe_allow_html=True)
    st.caption(f"Endring er mot foregående {state.window_hours}-timersvindu.")

    st.markdown("### Asset implications")
    assets = "".join(
        f"""
        <div class="ws-asset">
          <div class="ws-asset-name">{html.escape(item.asset)}</div>
          <div class="ws-asset-bias">{html.escape(item.bias)}</div>
          <div class="ws-asset-score">Score {item.score} · confidence {item.confidence}%</div>
        </div>
        """
        for item in state.asset_moods
    )
    st.markdown(f'<div class="ws-assets">{assets}</div>', unsafe_allow_html=True)

    st.markdown("### Measurement context")
    tone = "—" if state.average_tone is None else f"{state.average_tone:+.2f}"
    previous_tone = "—" if state.previous_average_tone is None else f"{state.previous_average_tone:+.2f}"
    st.write(
        f"Documents: **{state.document_count:,}** · previous: **{state.previous_document_count:,}** · "
        f"GDELT tone: **{tone}** · previous tone: **{previous_tone}**"
    )
    st.caption(
        f"Window: {state.window_start} → {state.window_end} · "
        f"processed {state.bytes_processed / 1024**2:.1f} MiB"
    )

    with st.expander("Evidence, interpretation and limitations"):
        st.write(
            "World State measures the state that became observable in global published coverage. "
            "It does not assume that coverage caused the market move."
        )
        for limitation in state.limitations:
            st.write(f"• {limitation}")


st.title("World State")
st.caption(
    "GDELT-based profile of the globally measurable news state, compared with the immediately preceding window."
)

with st.sidebar:
    st.header("World State")
    window_hours = st.selectbox("Window", [3, 6, 12, 24], index=2, format_func=lambda value: f"{value} hours")
    refresh = st.button("Update World State", type="primary", use_container_width=True)

state_key = f"world_state_{window_hours}"
if refresh:
    try:
        with st.spinner("Querying GDELT and building World State …"):
            st.session_state[state_key] = fetch_world_state(window_hours=window_hours)
    except Exception as exc:
        st.error(f"Could not build World State: {exc}")

state = st.session_state.get(state_key)
if state is None:
    st.info("Press «Update World State» to calculate the current global state profile.")
else:
    render_world_state(state)
