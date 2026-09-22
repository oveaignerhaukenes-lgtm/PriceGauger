from __future__ import annotations

import pandas as pd
import streamlit as st

from autotrader_pnl_comparison_v2 import AutoManagerPnlComparisonV2
from autotrader_v3_regime_returns_v1 import build_relative_return_lines_v3


def render_v3_regime_return_chart(
    comparison: AutoManagerPnlComparisonV2,
    *,
    bucket_count: int = 12,
) -> None:
    del bucket_count
    st.markdown("**V3 · relativ strategiavkastning**")
    st.caption(
        "Hver strategi starter på 0 og går kontinuerlig så langt over eller under null "
        "som avkastningen tilsier. Trykk på strateginavnet under grafen for detaljer."
    )
    points = build_relative_return_lines_v3(comparison)
    if not points:
        st.info("Venter på nok strategihistorikk til v3-grafen.")
        return

    frame = pd.DataFrame(
        {
            "Tid": [item.closed_at for item in points],
            "Strategi": [item.strategy_key for item in points],
            "Avkastning %": [item.return_pct for item in points],
        }
    )
    pivot = frame.pivot_table(
        index="Tid", columns="Strategi", values="Avkastning %", aggfunc="last"
    ).sort_index()
    if len(pivot.index) < 2:
        st.info("Venter på minst to tidspunkter før strategilinjene kan tegnes.")
    else:
        st.line_chart(pivot, x_label="Tid", y_label="Avkastning %", height=360)

    strategies = tuple(str(item) for item in pivot.columns)
    selected = st.selectbox(
        "Strategiinfo",
        ("Velg strategi …",) + strategies,
        key=f"v3_strategy_line_info_{comparison.product_key}",
    )
    if selected != "Velg strategi …":
        series = next((item for item in comparison.paper_series if item.strategy_key == selected), None)
        values = frame.loc[frame["Strategi"] == selected, "Avkastning %"]
        if series is not None and not values.empty:
            current = float(values.iloc[-1])
            best = float(values.max())
            worst = float(values.min())
            st.markdown(f"**{selected}**")
            c1, c2, c3 = st.columns(3)
            c1.metric("Nå", f"{current:+.2f}%")
            c2.metric("Beste", f"{best:+.2f}%")
            c3.metric("Laveste", f"{worst:+.2f}%")
            st.caption(
                f"{series.execution_mode} · start {series.started_at:%Y-%m-%d %H:%M} · "
                f"{len(series.points)} datapunkter"
            )


__all__ = ["render_v3_regime_return_chart"]
