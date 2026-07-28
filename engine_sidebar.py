from __future__ import annotations

import streamlit as st


_ENGINE_LABELS = {
    "historical": "Historisk motor",
    "technical": "Teknisk motor",
    "news": "Nyhetsmotor",
    "market_context": "Markedskontekst",
    "lagging_assets": "Etternølere",
    "synthesis": "Syntesemotor",
}


def render_engine_sidebar(*, active: str) -> None:
    with st.sidebar.expander("Motorer", expanded=True):
        st.page_link(
            "pages/1_Kjerneflyt.py",
            label=("● " if active == "historical" else "") + _ENGINE_LABELS["historical"],
        )
        st.page_link(
            "pages/2_Direct_Technical.py",
            label=("● " if active == "technical" else "") + _ENGINE_LABELS["technical"],
        )
        st.page_link(
            "pages/3_News_Context.py",
            label=("● " if active == "news" else "") + _ENGINE_LABELS["news"],
        )
        st.caption("Planlagt")
        st.write("Markedskontekst")
        st.write("Etternølere")
        st.write("Syntesemotor")
