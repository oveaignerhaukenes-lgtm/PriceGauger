from __future__ import annotations

import streamlit as st


LIGHTWEIGHT_TIMEFRAMES_V1: tuple[str, ...] = ("1m", "2m", "5m", "10m", "15m", "30m")


def _select_timeframe(state_key: str, value: str) -> None:
    st.session_state[state_key] = value


def render_lightweight_timeframe_toolbar_v1(*, state_key: str) -> None:
    """Render the compact TradingDesk chart-timeframe workbar."""

    current = str(st.session_state.get(state_key, "5m") or "5m")
    columns = st.columns(len(LIGHTWEIGHT_TIMEFRAMES_V1), gap="small")
    for column, value in zip(columns, LIGHTWEIGHT_TIMEFRAMES_V1):
        with column:
            st.button(
                value,
                key=f"pg-lightweight-timeframe:{value}",
                help=f"Vis chartet i {value}",
                type="primary" if current == value else "secondary",
                width="stretch",
                on_click=_select_timeframe,
                args=(state_key, value),
            )


__all__ = ["LIGHTWEIGHT_TIMEFRAMES_V1", "render_lightweight_timeframe_toolbar_v1"]
