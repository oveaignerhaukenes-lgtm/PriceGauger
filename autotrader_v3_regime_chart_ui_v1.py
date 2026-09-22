from __future__ import annotations

import pandas as pd
import streamlit as st

from autotrader_pnl_comparison_v2 import AutoManagerPnlComparisonV2
from autotrader_v3_regime_returns_v1 import build_regime_return_cells_v3


def render_v3_regime_return_chart(
    comparison: AutoManagerPnlComparisonV2,
    *,
    bucket_count: int = 12,
) -> None:
    st.markdown("**V3 · regimeavkastning rundt null**")
    st.caption(
        "Hver søyle er avkastningen i selve perioden, rebased til 0. "
        "Tidligere tap eller gevinst dras ikke med inn i neste regime."
    )
    cells = build_regime_return_cells_v3(comparison, bucket_count=bucket_count)
    if not cells:
        st.info("Venter på nok strategihistorikk til regimegrafen.")
        return

    frame = pd.DataFrame(
        {
            "Periode": [item.ended_at for item in cells],
            "Strategi": [item.strategy_key for item in cells],
            "Avkastning %": [item.return_pct for item in cells],
        }
    )
    pivot = frame.pivot_table(
        index="Periode", columns="Strategi", values="Avkastning %", aggfunc="last"
    ).sort_index()
    st.bar_chart(pivot, x_label="Periode", y_label="Avkastning %", stack=False)
    st.caption("Over 0 = lønnsomt regime · under 0 = tapsregime.")


__all__ = ["render_v3_regime_return_chart"]
