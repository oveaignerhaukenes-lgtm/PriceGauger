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
df["expected_ret"], df["residual"] = fit_model(df, include_dxy)
df["residual_20d"] = df["residual"].rolling(20, min_periods=5).sum() * 100
df["gold_norm"] = df["gold"] / df["gold"].iloc[0] * 100
# Invert real yield so the traditional gold relationship points in the same visual direction.
df["real_inverse_norm"] = 100 - (df["real_yield"] - df["real_yield"].iloc[0]) * 20

latest = df.dropna(subset=["beta_real"]).iloc[-1] if df["beta_real"].notna().any() else df.iloc[-1]
prev_beta = df["beta_real"].dropna().iloc[-min(21, df["beta_real"].notna().sum())] if df["beta_real"].notna().any() else np.nan
compression = abs(latest["beta_real"]) < abs(prev_beta) if pd.notna(prev_beta) else False

c1, c2, c3, c4 = st.columns(4)
c1.metric("10Y realrente", f'{latest["real_yield"]:.2f}%')
c2.metric("Rullerende realrente-beta", f'{latest["beta_real"]:.3f}' if pd.notna(latest["beta_real"]) else "—")
c3.metric("Korrelasjon", f'{latest["corr_real"]:.2f}' if pd.notna(latest["corr_real"]) else "—")
c4.metric("20d uforklart gullstyrke", f'{latest["residual_20d"]:+.2f}%' if pd.notna(latest["residual_20d"]) else "—")

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
fig_beta.add_trace(go.Scatter(x=df.index, y=df["beta_real"], name="Realrente-beta"))
fig_beta.add_hline(y=0, line_dash="dot")
fig_beta.update_layout(title=f"Rullerende {reg_window}d beta · mot null = kompresjon", height=340, yaxis_title="Beta")
st.plotly_chart(fig_beta, use_container_width=True)

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
