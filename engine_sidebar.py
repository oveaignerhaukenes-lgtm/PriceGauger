from __future__ import annotations

import streamlit as st


_SOURCE_LABELS = {
    "news": "Nyhetsanalyse",
    "telegram_flow": "Telegram-vurdering",
    "macro": "Makrokalender",
}


def render_engine_sidebar(*, active: str) -> None:
    """Render navigation only for active v2-era semantic source surfaces.

    Historical/Decision/Recommendation v1 pages are retired and must not be
    reachable through an active navigation helper.
    """
    with st.sidebar.expander("Analysekilder", expanded=True):
        st.page_link(
            "pages/3_News_Context.py",
            label=("● " if active == "news" else "") + _SOURCE_LABELS["news"],
        )
        st.page_link(
            "pages/4_Telegram_Flow.py",
            label=("● " if active == "telegram_flow" else "") + _SOURCE_LABELS["telegram_flow"],
        )
        st.page_link(
            "pages/8_Macro_Calendar.py",
            label=("● " if active == "macro" else "") + _SOURCE_LABELS["macro"],
        )
        st.caption("Semantiske kilder publiseres inn i canonical ContextSnapshotV2 før composition.")
