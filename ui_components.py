from __future__ import annotations

import html

import streamlit as st


def render_instrument_heading(asset: str, *, context: str = "") -> None:
    """Render a prominent, compact instrument identity above an analysis."""
    subtitle = f'<span class="pg-instrument-context">{html.escape(context)}</span>' if context else ""
    st.markdown(
        f"""
        <style>
        .pg-instrument-heading {{
            display:flex;
            align-items:baseline;
            gap:.75rem;
            padding:.55rem .75rem;
            margin:.15rem 0 .85rem;
            border-left:4px solid #ff4b4b;
            background:rgba(128,128,128,.055);
        }}
        .pg-instrument-name {{
            font-size:1.65rem;
            line-height:1;
            font-weight:750;
            letter-spacing:-.02em;
        }}
        .pg-instrument-context {{
            color:rgba(128,128,128,.95);
            font-size:.82rem;
            font-weight:600;
            text-transform:uppercase;
            letter-spacing:.04em;
        }}
        </style>
        <div class="pg-instrument-heading">
          <span class="pg-instrument-name">{html.escape(asset)}</span>{subtitle}
        </div>
        """,
        unsafe_allow_html=True,
    )
