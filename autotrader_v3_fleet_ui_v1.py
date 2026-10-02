from __future__ import annotations

import streamlit as st

from autotrader_execution_diagnostics_v1 import load_execution_diagnostic_v1
from autotrader_v3_fleet_read_model_v1 import TraderFleetRowV3


def render_autotrader_v3_fleet_preview(rows: tuple[TraderFleetRowV3, ...]) -> None:
    st.subheader("AutoTrader v3 · Fleet")
    st.caption("Read-only runtimevisning. Execution authority styres av V3 control-plane.")
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

            try:
                diagnostic = load_execution_diagnostic_v1(
                    account_id=snap.account.account_id,
                    uic=int(snap.account.uic),
                    asset_type=snap.account.asset_type,
                    owner_key=snap.trader_id,
                    engine_id="V3",
                )
            except Exception as exc:
                st.caption(f"Execution diagnostics: {exc}")
            else:
                with st.expander("Execution diagnostics", expanded=False):
                    st.caption(
                        f"Runtime: {diagnostic.runtime_status or '—'} · "
                        f"Request: {diagnostic.request_state or '—'}"
                    )
                    if diagnostic.runtime_detail:
                        st.code(diagnostic.runtime_detail, language=None)
                    if diagnostic.request_key:
                        st.caption(
                            f"request_key={diagnostic.request_key} · "
                            f"broker_order_id={diagnostic.broker_order_id or '—'} · "
                            f"expected={diagnostic.expected_inventory if diagnostic.expected_inventory is not None else '—'} · "
                            f"{diagnostic.submitted_side or '—'} "
                            f"{diagnostic.submitted_amount if diagnostic.submitted_amount is not None else '—'}"
                        )
                    if diagnostic.request_detail:
                        st.caption(diagnostic.request_detail)
                    st.caption(
                        f"runtime_updated={diagnostic.runtime_updated_at or '—'} · "
                        f"request_updated={diagnostic.request_updated_at or '—'}"
                    )


__all__ = ["render_autotrader_v3_fleet_preview"]
