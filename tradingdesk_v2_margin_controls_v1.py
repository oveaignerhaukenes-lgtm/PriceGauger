from __future__ import annotations

import streamlit as st

from autotrader_entry_policy_v2 import load_pilot_margin_config_v2, save_pilot_margin_config_v2


def render_v2_margin_controls_v1(*, pilot_key: str, currency: str, allocated_capital: float) -> None:
    """Render the canonical V2 Margin Envelope controls without changing execution semantics."""
    config = load_pilot_margin_config_v2(pilot_key)
    if config is None:
        st.warning("Margin Envelope mangler. Slå LIVE av/på for å provisionere standardrammen før ny entry.")
        return

    st.divider()
    st.markdown("**Margin Envelope**")
    st.caption("Hard grense for ny eksponering. Saxo-precheck er fortsatt siste autoritet før hver OPEN/ADD.")
    max_leverage = st.number_input(
        "Maks effektiv gearing",
        min_value=0.01,
        value=float(config.max_effective_leverage),
        step=0.5,
        format="%.2f",
        key=f"td-simple-margin-leverage:{pilot_key}",
        help="Maks brutto nominell eksponering delt på pilotens kontrollerte kapital.",
    )
    max_buffer = max(0.0, float(allocated_capital) - 0.01)
    free_buffer = st.number_input(
        f"Fri-margin-buffer ({currency})",
        min_value=0.0,
        max_value=max_buffer,
        value=min(float(config.minimum_free_capital), max_buffer),
        step=100.0,
        format="%.2f",
        key=f"td-simple-margin-free:{pilot_key}",
        help="Kapital som alltid skal stå fri etter en ny OPEN/ADD.",
    )
    if st.button("Lagre Margin Envelope", key=f"td-simple-margin-save:{pilot_key}", width="stretch"):
        save_pilot_margin_config_v2(
            pilot_key=pilot_key,
            max_effective_leverage=float(max_leverage),
            minimum_free_capital=float(free_buffer),
            enabled=True,
        )
        st.success("Margin Envelope er oppdatert. Neste OPEN/ADD bruker den nye rammen og revalideres av Saxo.")
        st.rerun()
