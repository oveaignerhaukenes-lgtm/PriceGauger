from __future__ import annotations

import streamlit as st


LIGHTWEIGHT_TIMEFRAMES_V1: tuple[str, ...] = ("1m", "2m", "5m", "10m", "15m", "30m")
_TOOLBAR_KEY = "pg-lightweight-timeframe-toolbar"
_TOOLBAR_CSS = f"""
<style>
.st-key-{_TOOLBAR_KEY} div[data-testid="stHorizontalBlock"] {{
    display: flex !important;
    flex-wrap: nowrap !important;
    gap: .22rem !important;
    align-items: center !important;
    overflow-x: auto !important;
    overflow-y: hidden !important;
    scrollbar-width: none !important;
    padding: .05rem 0 .18rem 0 !important;
}}
.st-key-{_TOOLBAR_KEY} div[data-testid="stHorizontalBlock"]::-webkit-scrollbar {{
    display: none !important;
}}
.st-key-{_TOOLBAR_KEY} div[data-testid="stColumn"] {{
    flex: 0 0 auto !important;
    width: auto !important;
    min-width: 2.45rem !important;
}}
.st-key-{_TOOLBAR_KEY} div[data-testid="stColumn"] > div {{
    width: auto !important;
}}
.st-key-{_TOOLBAR_KEY} .stButton {{
    margin: 0 !important;
}}
.st-key-{_TOOLBAR_KEY} .stButton > button {{
    width: auto !important;
    min-width: 2.45rem !important;
    min-height: 1.78rem !important;
    height: 1.78rem !important;
    padding: 0 .48rem !important;
    border-radius: .42rem !important;
    font-size: .78rem !important;
    line-height: 1 !important;
    white-space: nowrap !important;
}}
</style>
"""


def _select_timeframe(state_key: str, value: str) -> None:
    st.session_state[state_key] = value


def render_lightweight_timeframe_toolbar_v1(*, state_key: str) -> None:
    """Render one compact, non-wrapping TradingDesk timeframe workbar."""

    current = str(st.session_state.get(state_key, "5m") or "5m")
    st.markdown(_TOOLBAR_CSS, unsafe_allow_html=True)
    with st.container(key=_TOOLBAR_KEY):
        columns = st.columns(len(LIGHTWEIGHT_TIMEFRAMES_V1), gap="small")
        for column, value in zip(columns, LIGHTWEIGHT_TIMEFRAMES_V1):
            with column:
                st.button(
                    value,
                    key=f"pg-lightweight-timeframe:{value}",
                    help=f"Vis chartet i {value}",
                    type="primary" if current == value else "secondary",
                    on_click=_select_timeframe,
                    args=(state_key, value),
                )


__all__ = ["LIGHTWEIGHT_TIMEFRAMES_V1", "render_lightweight_timeframe_toolbar_v1"]
