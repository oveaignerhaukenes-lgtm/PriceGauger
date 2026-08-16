from __future__ import annotations

from typing import Literal

import streamlit as st

MigrationAuthority = Literal["V2", "LEGACY/V1", "MIXED"]

_COLORS: dict[MigrationAuthority, str] = {
    "V2": "#16a34a",
    "LEGACY/V1": "#2563eb",
    "MIXED": "#2563eb",
}


def render_migration_badge(
    authority: MigrationAuthority,
    *,
    storage: str = "PostgreSQL",
    detail: str | None = None,
) -> None:
    """Temporary page-level migration marker; remove after the v1 cutover is complete."""
    color = _COLORS[authority]
    suffix = f" · {storage}" if storage else ""
    st.markdown(
        f'<div style="font-size:.72rem;font-weight:700;color:{color};margin:-.15rem 0 .35rem 0;">'
        f'DATA: {authority}{suffix}</div>',
        unsafe_allow_html=True,
    )
    if detail:
        st.caption(detail)


def render_legacy_source_note(label: str = "Legacy/V1 source — migration pending") -> None:
    """Temporary section-level marker for data still produced/read through legacy paths."""
    st.markdown(
        f'<div style="font-size:.72rem;color:#2563eb;margin:.08rem 0 .28rem 0;">{label}</div>',
        unsafe_allow_html=True,
    )
