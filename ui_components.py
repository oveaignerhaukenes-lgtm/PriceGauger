from __future__ import annotations

import html

import streamlit as st


PIPELINE_STEPS = (
    "Analysis Input",
    "GDELT / Historical Event Lab",
    "World State",
    "Direct Technical",
    "Combined",
)


def render_pipeline_breadcrumb() -> None:
    """Render a compact, non-dominant reminder of the analysis pipeline."""
    path = " → ".join(PIPELINE_STEPS)
    st.markdown(
        f"""
        <style>
        .pg-pipeline-label {{
            margin:.1rem 0 .1rem;
            color:rgba(128,128,128,.82);
            font-size:.64rem;
            font-weight:700;
            letter-spacing:.09em;
            text-transform:uppercase;
        }}
        .pg-pipeline-path {{
            margin:0 0 .62rem;
            color:rgba(128,128,128,.92);
            font-size:.73rem;
            line-height:1.35;
            overflow-wrap:anywhere;
        }}
        </style>
        <div class="pg-pipeline-label">Analysis pipeline</div>
        <div class="pg-pipeline-path">{html.escape(path)}</div>
        """,
        unsafe_allow_html=True,
    )


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
