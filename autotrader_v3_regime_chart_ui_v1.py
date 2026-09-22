from __future__ import annotations

import html
import math
import pandas as pd
import streamlit as st

from autotrader_pnl_comparison_v2 import AutoManagerPnlComparisonV2
from autotrader_v3_regime_returns_v1 import build_regime_reset_return_lines_v3


def _svg_chart(pivot: pd.DataFrame) -> str:
    width, height = 1000.0, 360.0
    left, right, top, bottom = 62.0, 18.0, 18.0, 38.0
    values = [float(v) for col in pivot.columns for v in pivot[col].dropna().tolist() if math.isfinite(float(v))]
    if not values:
        return ""
    low, high = min(values + [0.0]), max(values + [0.0])
    span = max(high - low, 0.01)
    low -= span * .08
    high += span * .08
    plot_w, plot_h = width-left-right, height-top-bottom
    times = list(pivot.index)
    def x(i: int) -> float:
        return left if len(times) <= 1 else left + plot_w * i / (len(times)-1)
    def y(v: float) -> float:
        return top + plot_h * (high-v)/(high-low)
    palette = ("#60a5fa","#f59e0b","#34d399","#f472b6","#a78bfa","#22d3ee","#fb7185","#a3e635","#facc15","#c084fc","#2dd4bf","#94a3b8")
    lines=[]
    for ci,col in enumerate(pivot.columns):
        pts=[]
        for i,val in enumerate(pivot[col].tolist()):
            if pd.notna(val) and math.isfinite(float(val)):
                pts.append(f"{x(i):.1f},{y(float(val)):.1f}")
        if len(pts) >= 2:
            lines.append(f'<polyline points="{" ".join(pts)}" fill="none" stroke="{palette[ci % len(palette)]}" stroke-width="1.35" vector-effect="non-scaling-stroke"/>')
    zero=y(0.0)
    return f"""<div style="width:100%;overflow:hidden;margin:.2rem 0 .6rem">
<svg viewBox="0 0 1000 360" width="100%" height="360" preserveAspectRatio="none" role="img" aria-label="Relativ strategiavkastning">
<line x1="{left}" y1="{zero:.1f}" x2="{width-right}" y2="{zero:.1f}" stroke="rgba(148,163,184,.55)" stroke-width="1" stroke-dasharray="6 5"/>
<text x="8" y="{max(14,zero+5):.1f}" fill="currentColor" opacity=".7" font-size="18">0%</text>
<text x="8" y="{top+10:.1f}" fill="currentColor" opacity=".65" font-size="16">{high:+.1f}%</text>
<text x="8" y="{height-bottom:.1f}" fill="currentColor" opacity=".65" font-size="16">{low:+.1f}%</text>
{"".join(lines)}
</svg></div>"""


def render_v3_regime_return_chart(comparison: AutoManagerPnlComparisonV2, *, bucket_count: int = 12) -> None:
    st.markdown("**V3 · relativ strategiavkastning**")
    st.caption("Hver strategi nullstilles ved hvert regime. Linjen viser gevinst eller tap siden starten av gjeldende regime, slik at et nytt regime vurderes uavhengig av tidligere gevinst eller tap.")
    points = build_regime_reset_return_lines_v3(comparison, bucket_count=bucket_count)
    if not points:
        st.info("Venter på strategihistorikk til v3-grafen.")
        return
    frame=pd.DataFrame({"Tid":[p.closed_at for p in points],"Strategi":[p.strategy_key for p in points],"Avkastning %":[p.return_pct for p in points]})
    pivot=frame.pivot_table(index="Tid",columns="Strategi",values="Avkastning %",aggfunc="last").sort_index()
    chart=_svg_chart(pivot)
    if chart:
        st.markdown(chart, unsafe_allow_html=True)
    else:
        st.info("Venter på gyldige datapunkter til v3-grafen.")

    strategies=tuple(str(item) for item in pivot.columns)
    selected=st.selectbox("Strategiinfo",("Velg strategi …",)+strategies,key=f"v3_strategy_line_info_{comparison.product_key}")
    if selected != "Velg strategi …":
        series=next((item for item in comparison.paper_series if item.strategy_key==selected),None)
        values=frame.loc[frame["Strategi"]==selected,"Avkastning %"]
        if series is not None and not values.empty:
            current,best,worst=float(values.iloc[-1]),float(values.max()),float(values.min())
            st.markdown(f"**{html.escape(selected)}**")
            c1,c2,c3=st.columns(3); c1.metric("Nå",f"{current:+.2f}%"); c2.metric("Beste",f"{best:+.2f}%"); c3.metric("Laveste",f"{worst:+.2f}%")
            st.caption(f"{series.execution_mode} · start {series.started_at:%Y-%m-%d %H:%M} · {len(series.points)} datapunkter")
    st.caption("Alle strategier nullstilles ved regimeskifte. +5 % i forrige regime etterfulgt av -3 % i neste vises derfor som -3 %, ikke +2 %.")


__all__=["render_v3_regime_return_chart"]
