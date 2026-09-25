"""Visible opt-in switches for non-strategy automated exits."""

import streamlit as st

from autotrader_modifier_authority_v1 import modifier_enabled_v1, set_modifier_enabled_v1
from database import using_postgres


def render_modifier_authority_v1() -> None:
    st.subheader("Automatiske tillegg")
    st.caption("Ren strategi er standard. Disse reglene kan lukke posisjoner mellom strategiens signaler. Valgene gjelder alle v2-piloter.")
    if not using_postgres():
        st.info("Bryterne krever PostgreSQL.")
        return
    for name, label in (
        ("breakeven_reset", "Breakeven Reset"),
        ("position_guardian", "Position Guardian (stopp, trailing og gevinstmål)"),
        ("take_profit", "X + TakeProfit"),
    ):
        try:
            active = modifier_enabled_v1(name)
            selected = st.toggle(label, value=active, key=f"v2-modifier-{name}")
            if selected != active:
                set_modifier_enabled_v1(name, selected)
                st.rerun()
        except Exception as exc:
            st.error(f"Kunne ikke laste {label}: {exc}")
