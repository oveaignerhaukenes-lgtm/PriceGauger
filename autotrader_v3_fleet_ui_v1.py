from __future__ import annotations

import streamlit as st

from autotrader_v3_fleet_read_model_v1 import TraderFleetRowV3


def render_autotrader_v3_fleet_preview(rows: tuple[TraderFleetRowV3, ...]) -> None:
    st.subheader("AutoTrader v3 · Fleet")
    st.caption("Read-only migreringsvisning. V3 har ingen ordreautoritet her.")
    if not rows:
        st.info("Ingen tradere å projisere til v3 ennå.")
        return

    for row in rows:
        snap = row.snapshot
        status = "PÅ" if row.enabled else "AV"
        with st.container(border=True):
            left, right = st.columns([3, 1])
            with left:
                st.markdown(f"**{snap.trader_id}**")
                st.caption(
                    f"Konto {snap.account.account_id} · UIC {snap.account.uic} · "
                    f"{snap.account.asset_type}"
                )
            with right:
                st.metric("Kapital", f"{snap.capital_allocation.tradeable_pct:.0f}%")
            st.markdown(row.truth_line)
            st.caption(f"{status} · {row.execution_mode} · {snap.mode.value}")


__all__ = ["render_autotrader_v3_fleet_preview"]
