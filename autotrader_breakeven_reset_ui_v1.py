from __future__ import annotations

import streamlit as st

from autotrader_breakeven_reset_v1 import (
    BreakevenResetConfigV1,
    load_breakeven_reset_config_v1,
    save_breakeven_reset_config_v1,
)


def render_breakeven_reset_controls_v1() -> None:
    st.subheader("Breakeven reset")
    st.caption(
        "Global AutoManage-regel for alle modeller. Etter at en posisjon først har vært i pluss, "
        "går den FLAT når den returnerer til entry-sonen. Ny OPEN er blokkert i cooldown-perioden "
        "etter bekreftet FLAT, slik at strategien må vurderes på nytt i stedet for å gjenbruke et gammelt signal."
    )
    try:
        config = load_breakeven_reset_config_v1()
    except Exception as exc:
        st.info(f"Breakeven reset venter på runtime-initialisering: {exc}")
        return

    with st.form("autotrader_breakeven_reset_config_v1"):
        enabled = st.checkbox(
            "Aktiver global Breakeven reset",
            value=bool(config.enabled),
            help="Gjelder alle nåværende og fremtidige AutoManage-strategier som bruker den felles execution-pathen.",
        )
        c1, c2, c3 = st.columns(3)
        min_favourable_bps = c1.number_input(
            "Armer etter profit (bps)",
            min_value=0.0,
            max_value=100.0,
            value=float(config.min_favourable_bps),
            step=0.5,
            format="%.1f",
            help="2 bps = 0,02 % posisjonsavkastning. Hindrer at spread rundt en helt fersk entry utløser reset.",
        )
        breakeven_band_bps = c2.number_input(
            "Entry-band (bps)",
            min_value=0.0,
            max_value=50.0,
            value=float(config.breakeven_band_bps),
            step=0.5,
            format="%.1f",
            help="Når en armert posisjon faller tilbake til eller under dette positive båndet, går den FLAT.",
        )
        cooldown_seconds = c3.number_input(
            "Cooldown etter FLAT (sek)",
            min_value=1,
            max_value=900,
            value=int(config.cooldown_seconds),
            step=5,
            help="Tiden regnes fra bekreftet close/equity-reconciliation, ikke fra selve triggeren.",
        )
        saved = st.form_submit_button("Lagre Breakeven reset", use_container_width=True)

    if saved:
        try:
            save_breakeven_reset_config_v1(
                BreakevenResetConfigV1(
                    enabled=bool(enabled),
                    cooldown_seconds=int(cooldown_seconds),
                    min_favourable_bps=float(min_favourable_bps),
                    breakeven_band_bps=float(breakeven_band_bps),
                )
            )
            st.success("Breakeven reset er lagret globalt.")
            st.rerun()
        except Exception as exc:
            st.error(f"Kunne ikke lagre Breakeven reset: {exc}")
