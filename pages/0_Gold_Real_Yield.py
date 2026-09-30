from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf

st.set_page_config(page_title="Gold × Real Yield", page_icon="🧭", layout="wide")
st.title("Gold × Real Yield · beta compression")
st.caption("Viser om gull følger den historiske realrente-/dollarrelasjonen, eller begynner å fortelle en annen historie.")

PERIODS = {"30d": "3mo", "90d": "6mo", "1y": "2y", "3y": "5y", "5y": "10y"}
window_label = st.segmented_control("Analysehorisont", list(PERIODS), default="1y")
reg_window = st.slider("Rullerende beta (handelsdager)", 20, 126, 60, 5)
include_dxy = st.toggle("Kontroller også for DXY", value=True)

@st.cache_data(ttl=1800, show_spinner=False)
def load_market(period: str) -> pd.DataFrame:
    raw = yf.download(["GC=F", "DX-Y.NYB"], period=period, interval="1d", auto_adjust=False, progress=False)
    if raw.empty:
        return pd.DataFrame()
    close = raw["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw
    out = pd.DataFrame(index=close.index)
    out["gold"] = close["GC=F"] if "GC=F" in close else np.nan
    out["dxy"] = close["DX-Y.NYB"] if "DX-Y.NYB" in close else np.nan
    return out.dropna(how="all")

@st.cache_data(ttl=21600, show_spinner=False)
def load_fred(series: str) -> pd.Series:
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"
    frame = pd.read_csv(url, na_values=".")
    frame.columns = ["date", series]
    frame["date"] = pd.to_datetime(frame["date"])
    return frame.set_index("date")[series].astype(float)

def fit_model(frame: pd.DataFrame, use_dxy: bool) -> tuple[pd.Series, pd.Series]:
    y = frame["gold_ret"]
    cols = ["real_yield_chg"] + (["dxy_ret"] if use_dxy else [])
    x = frame[cols]
    valid = pd.concat([y, x], axis=1).dropna()
    expected = pd.Series(index=frame.index, dtype=float)
    residual = pd.Series(index=frame.index, dtype=float)
    if len(valid) < 15:
        return expected, residual
    X = np.column_stack([np.ones(len(valid)), valid[cols].to_numpy()])
    coef, *_ = np.linalg.lstsq(X, valid["gold_ret"].to_numpy(), rcond=None)
    expected.loc[valid.index] = X @ coef
    residual.loc[valid.index] = valid["gold_ret"] - expected.loc[valid.index]
    return expected, residual

market = load_market(PERIODS[window_label])
real_yield = load_fred("DFII10").rename("real_yield")
breakeven = load_fred("T10YIE").rename("breakeven")

df = market.join(real_yield, how="outer").join(breakeven, how="outer").sort_index()
df[["gold", "dxy"]] = df[["gold", "dxy"]].ffill(limit=3)
df[["real_yield", "breakeven"]] = df[["real_yield", "breakeven"]].ffill(limit=5)
df = df.dropna(subset=["gold", "real_yield"]).copy()
df["gold_ret"] = np.log(df["gold"]).diff()
df["dxy_ret"] = np.log(df["dxy"]).diff()
df["real_yield_chg"] = df["real_yield"].diff()

# Rolling beta: gold log return per +1 percentage-point move in 10Y real yield.
df["beta_real"] = df["gold_ret"].rolling(reg_window).cov(df["real_yield_chg"]) / df["real_yield_chg"].rolling(reg_window).var()
df["corr_real"] = df["gold_ret"].rolling(reg_window).corr(df["real_yield_chg"])

def rolling_conditional_beta(frame: pd.DataFrame, direction: int) -> pd.Series:
    values = pd.Series(index=frame.index, dtype=float)
    for end in range(reg_window - 1, len(frame)):
        sample = frame.iloc[end - reg_window + 1:end + 1]
        sample = sample[sample["real_yield_chg"] * direction > 0].dropna(subset=["gold_ret", "real_yield_chg"])
        if len(sample) < max(6, reg_window // 5) or sample["real_yield_chg"].var() == 0:
            continue
        values.iloc[end] = sample["gold_ret"].cov(sample["real_yield_chg"]) / sample["real_yield_chg"].var()
    return values

df["beta_yield_up"] = rolling_conditional_beta(df, 1)
df["beta_yield_down"] = rolling_conditional_beta(df, -1)
df["expected_ret"], df["residual"] = fit_model(df, include_dxy)
df["residual_20d"] = df["residual"].rolling(20, min_periods=5).sum() * 100
df["gold_norm"] = df["gold"] / df["gold"].iloc[0] * 100
# Invert real yield so the traditional gold relationship points in the same visual direction.
df["real_inverse_norm"] = 100 - (df["real_yield"] - df["real_yield"].iloc[0]) * 20

latest = df.dropna(subset=["beta_real"]).iloc[-1] if df["beta_real"].notna().any() else df.iloc[-1]
prev_beta = df["beta_real"].dropna().iloc[-min(21, df["beta_real"].notna().sum())] if df["beta_real"].notna().any() else np.nan
compression = abs(latest["beta_real"]) < abs(prev_beta) if pd.notna(prev_beta) else False
latest_up = df["beta_yield_up"].dropna().iloc[-1] if df["beta_yield_up"].notna().any() else np.nan
latest_down = df["beta_yield_down"].dropna().iloc[-1] if df["beta_yield_down"].notna().any() else np.nan

def regime_label(beta: float, previous: float) -> str:
    if pd.isna(beta):
        return "Utilstrekkelig data"
    if beta > 0:
        return "Inversjon"
    if pd.notna(previous) and abs(beta) < abs(previous) * 0.75:
        return "Kompresjon"
    if abs(beta) < 0.03:
        return "Nær dekobling"
    return "Normal negativ beta"

regime = regime_label(latest["beta_real"], prev_beta)

c1, c2, c3, c4 = st.columns(4)
c1.metric("10Y realrente", f'{latest["real_yield"]:.2f}%')
c2.metric("Rullerende realrente-beta", f'{latest["beta_real"]:.3f}' if pd.notna(latest["beta_real"]) else "—")
c3.metric("Korrelasjon", f'{latest["corr_real"]:.2f}' if pd.notna(latest["corr_real"]) else "—")
c4.metric(f"20d uforklart gullstyrke · {regime}", f'{latest["residual_20d"]:+.2f}%' if pd.notna(latest["residual_20d"]) else "—")

if pd.notna(prev_beta):
    if compression:
        st.info("Beta compression: gulls følsomhet for realrenten er svakere enn for omtrent 20 handelsdager siden.")
    else:
        st.info("Ingen beta-kompresjon akkurat nå: realrentefølsomheten er like sterk eller sterkere enn for omtrent 20 handelsdager siden.")

fig = go.Figure()
fig.add_trace(go.Scatter(x=df.index, y=df["gold_norm"], name="Gull (indeks=100)"))
fig.add_trace(go.Scatter(x=df.index, y=df["real_inverse_norm"], name="Invertert 10Y realrente (visuell indeks)"))
fig.update_layout(title="Gull mot invertert realrente", hovermode="x unified", height=420, yaxis_title="Normalisert")
st.plotly_chart(fig, use_container_width=True)

fig_beta = go.Figure()
# Regime bands are descriptive visual guides, not statistical thresholds.
fig_beta.add_hrect(y0=-10, y1=-0.10, fillcolor="rgba(255,80,80,0.07)", line_width=0, annotation_text="normal negativ følsomhet", annotation_position="top left")
fig_beta.add_hrect(y0=-0.10, y1=-0.03, fillcolor="rgba(255,190,0,0.10)", line_width=0, annotation_text="kompresjon", annotation_position="top left")
fig_beta.add_hrect(y0=-0.03, y1=0.03, fillcolor="rgba(80,160,255,0.10)", line_width=0, annotation_text="nær dekobling", annotation_position="top left")
fig_beta.add_hrect(y0=0.03, y1=10, fillcolor="rgba(80,200,120,0.08)", line_width=0, annotation_text="inversjon", annotation_position="bottom left")
fig_beta.add_trace(go.Scatter(x=df.index, y=df["beta_real"], name="Realrente-beta"))
fig_beta.add_hline(y=0, line_dash="dot")
fig_beta.update_layout(title=f"Rullerende {reg_window}d beta · mot null = kompresjon", height=340, yaxis_title="Beta")
st.plotly_chart(fig_beta, use_container_width=True)

fig_asym = go.Figure()
fig_asym.add_trace(go.Scatter(x=df.index, y=df["beta_yield_up"], name="β · realrente stiger"))
fig_asym.add_trace(go.Scatter(x=df.index, y=df["beta_yield_down"], name="β · realrente faller"))
fig_asym.add_hline(y=0, line_dash="dot")
fig_asym.update_layout(title="Asymmetrisk beta · reagerer gull ulikt på rente opp og rente ned?", height=360, yaxis_title="Beta", hovermode="x unified")
st.plotly_chart(fig_asym, use_container_width=True)

if pd.notna(latest_up) and pd.notna(latest_down):
    asym = abs(latest_up) - abs(latest_down)
    if abs(latest_up) < abs(latest_down):
        st.caption(f"Asymmetri nå: gull er mindre følsomt når realrenten stiger enn når den faller (|β opp| − |β ned| = {asym:+.3f}).")
    else:
        st.caption(f"Asymmetri nå: ingen defensiv kompresjon på opp-rentedager (|β opp| − |β ned| = {asym:+.3f}).")

fig_res = go.Figure()
fig_res.add_trace(go.Scatter(x=df.index, y=df["residual_20d"], name="20d residual"))
fig_res.add_hline(y=0, line_dash="dot")
fig_res.update_layout(title="Uforklart gullstyrke · kumulativ modellresidual", height=340, yaxis_title="%")
st.plotly_chart(fig_res, use_container_width=True)

with st.expander("Realrente = nominell rente − inflasjonsforventning"):
    comp = df.dropna(subset=["real_yield", "breakeven"]).copy()
    comp["synthetic_nominal"] = comp["real_yield"] + comp["breakeven"]
    f = go.Figure()
    f.add_trace(go.Scatter(x=comp.index, y=comp["real_yield"], name="DFII10 · realrente"))
    f.add_trace(go.Scatter(x=comp.index, y=comp["breakeven"], name="T10YIE · breakeven"))
    f.add_trace(go.Scatter(x=comp.index, y=comp["synthetic_nominal"], name="Real + breakeven"))
    f.update_layout(height=350, hovermode="x unified", yaxis_title="%")
    st.plotly_chart(f, use_container_width=True)

st.caption("Kilder: FRED DFII10/T10YIE og Yahoo Finance GC=F/DX-Y.NYB. FRED realrente er daglig, ikke intradag. Residualen er diagnostikk, ikke et kursmål.")
