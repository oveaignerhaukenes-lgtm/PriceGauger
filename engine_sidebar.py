from __future__ import annotations

import streamlit as st

from migration_debug_ui import render_migration_badge


_ENGINE_LABELS = {
    "historical": "Historisk motor",
    "technical": "Teknisk motor",
    "news": "Nyhetsmotor",
    "telegram_flow": "Telegram Flow",
    "ai_assessment": "AI-markedsvurdering",
    "market_context": "Markedskontekst",
    "lagging_assets": "Etternølere",
    "synthesis": "Syntesemotor",
}

_LEGACY_DETAILS = {
    "historical": "Historisk motor ligger fortsatt på legacy/V1-kontraktene mens gjenbrukbare deler vurderes for v2.",
    "technical": "Legacy direkte teknisk motor. Autoritativ live Technical Core ligger i v2.",
    "news": "Nyhetskontekst produseres fortsatt av legacy/V1 worker/store og skal migreres lagvis.",
    "telegram_flow": "Telegram ingestion/scoring/store er fortsatt legacy/V1 og beholdes under kontrollert migrasjon.",
    "ai_assessment": "AI-markedsvurderingen er fortsatt koblet til legacy/V1 state/context.",
}


def render_engine_sidebar(*, active: str) -> None:
    render_migration_badge(
        "LEGACY/V1",
        detail=_LEGACY_DETAILS.get(active, "Legacy/V1 engine surface — migration pending."),
    )

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
        st.page_link(
            "pages/4_Telegram_Flow.py",
            label=("● " if active == "telegram_flow" else "") + _ENGINE_LABELS["telegram_flow"],
        )
        st.page_link(
            "pages/5_AI_Market_Assessment.py",
            label=("● " if active == "ai_assessment" else "") + _ENGINE_LABELS["ai_assessment"],
        )
        st.caption("Planlagt")
        st.write("Markedskontekst")
        st.write("Etternølere")
        st.write("Syntesemotor")
