from __future__ import annotations

import streamlit as st


LIGHTWEIGHT_TIMEFRAMES_V1: tuple[str, ...] = ("1m", "2m", "5m", "10m", "15m", "30m")


def _sync_timeframe(state_key: str, widget_key: str) -> None:
    value = st.session_state.get(widget_key)
    if value in LIGHTWEIGHT_TIMEFRAMES_V1:
        st.session_state[state_key] = value


def render_lightweight_timeframe_toolbar_v1(*, state_key: str) -> None:
    """Render one compact, non-wrapping TradingDesk timeframe workbar."""

    current = str(st.session_state.get(state_key, "5m") or "5m")
    if current not in LIGHTWEIGHT_TIMEFRAMES_V1:
        current = "5m"
        st.session_state[state_key] = current

    widget_key = f"{state_key}__lightweight_segmented"
    if st.session_state.get(widget_key) != current:
        st.session_state[widget_key] = current

    st.segmented_control(
        "Chart timeframe",
        options=LIGHTWEIGHT_TIMEFRAMES_V1,
        selection_mode="single",
        required=True,
        key=widget_key,
        label_visibility="collapsed",
        width="content",
        wrap=False,
        on_change=_sync_timeframe,
        args=(state_key, widget_key),
    )


__all__ = ["LIGHTWEIGHT_TIMEFRAMES_V1", "render_lightweight_timeframe_toolbar_v1"]
