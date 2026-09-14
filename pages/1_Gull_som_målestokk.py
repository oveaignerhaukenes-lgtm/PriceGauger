from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from build_info import render_build_badge
from gold_numeraire import (
    DEFAULT_ASSETS,
    GOLD_TICKER,
    PERIOD_OPTIONS,
    asset_map,
    build_numeraire_frame,
    dollar_in_gold_index,
    fetch_close,
    latest_comparison,
    normalized_usd_price,
)


st.set_page_config(page_title="Gull som målestokk · PriceGauger", page_icon="🥇", layout="wide")
render_build_badge()

st.title("Gull som målestokk")
st.caption(
    "Et numeraire-verktøy: se dollar og markeder målt i gull i stedet for å anta at USD er en stabil linjal. "
    "Alle serier indekseres til 100 ved starten av valgt periode."
)

assets = asset_map()
period_col, asset_col = st.columns([1, 3])
with period_col:
    period_label = st.selectbox("Periode", list(PERIOD_OPTIONS), index=3)
    period = PERIOD_OPTIONS[period_label]
with asset_col:
    default_labels = ["S&P 500", "Silver", "Brent oil", "Bitcoin"]
    selected_labels = st.multiselect(
        "Sammenlign med gull",
        [item.label for item in DEFAULT_ASSETS if item.ticker != "USD_GOLD"],
        default=default_labels,
        help="Linjen viser aktivets verdi relativt til gull. 80 betyr at aktivet har mistet 20 % mot gull siden periodens start.",
    )


@st.cache_data(ttl=900, show_spinner=False)
def _history(ticker: str, selected_period: str) -> pd.Series:
    return fetch_close(ticker, period=selected_period)


try:
    gold = _history(GOLD_TICKER, period)
except Exception as exc:
    st.error(f"Kunne ikke hente gullhistorikk: {exc}")
    st.stop()

prices: dict[str, pd.Series] = {}
errors: list[str] = []
for label in selected_labels:
    item = assets[label]
    try:
        prices[label] = _history(item.ticker, period)
    except Exception as exc:
        errors.append(f"{label}: {exc}")

if errors:
    with st.expander("Datakilder som ikke svarte", expanded=False):
        for error in errors:
            st.caption(error)

frame = build_numeraire_frame(prices, gold=gold, include_dollar=True)
if frame.empty:
    st.info("Ingen sammenlignbare serier er tilgjengelige for valgt periode.")
    st.stop()

left, right = st.columns([3, 2], gap="large")

with left:
    st.subheader("Markedet målt i gull")
    fig = go.Figure()
    for column in frame.columns:
        fig.add_trace(
            go.Scatter(
                x=frame.index,
                y=frame[column],
                mode="lines",
                name=column,
                connectgaps=False,
                hovertemplate="%{x|%Y-%m-%d}<br>%{y:.2f}<extra>%{fullData.name}</extra>",
            )
        )
    fig.add_hline(y=100.0, line_dash="dot", opacity=0.45)
    fig.update_layout(
        height=560,
        margin=dict(l=10, r=10, t=20, b=10),
        yaxis_title="Verdi relativt til gull · start = 100",
        xaxis_title=None,
        legend_title=None,
        hovermode="x unified",
    )
    st.plotly_chart(fig, use_container_width=True, config={"displaylogo": False})
    st.caption(
        "Fallende linje = aktivet eller dollaren mister verdi mot gull. Stigende linje = aktivet vinner verdi mot gull. "
        "US dollar-serien er 1/gullprisen, normalisert til 100."
    )

with right:
    st.subheader("Hva har endret seg?")
    dollar_gold = dollar_in_gold_index(gold)
    latest_dollar = float(dollar_gold.iloc[-1])
    st.metric(
        "USD kjøpekraft i gull",
        f"{latest_dollar:.1f}",
        f"{latest_dollar - 100.0:+.1f}%",
        help="Starten av valgt periode = 100. Et fall betyr at én dollar kjøper mindre gull.",
    )

    rows: list[dict[str, object]] = []
    for label, series in prices.items():
        try:
            comparison = latest_comparison(series, gold)
        except Exception:
            continue
        rows.append(
            {
                "Marked": label,
                "I USD": comparison["usd_change_pct"],
                "I gull": comparison["gold_change_pct"],
            }
        )
    if rows:
        table = pd.DataFrame(rows).set_index("Marked")
        st.dataframe(
            table.style.format({"I USD": "{:+.1f}%", "I gull": "{:+.1f}%"}),
            use_container_width=True,
        )
        st.caption(
            "Eksempel: et marked kan være +20 % i USD, men -10 % i gull. Da har nominell dollarpris steget samtidig som aktivet har tapt relativ kjøpekraft mot gull."
        )

st.divider()
st.subheader("USD-visning vs gull-visning")
focus_options = [label for label in selected_labels if label in prices]
if focus_options:
    focus = st.selectbox("Detaljmarked", focus_options)
    asset = prices[focus]
    usd_index = normalized_usd_price(asset).rename("Målt i USD")
    gold_index = frame[focus].dropna().rename("Målt i gull")
    detail = pd.concat([usd_index, gold_index], axis=1)

    detail_fig = go.Figure()
    for column in detail.columns:
        detail_fig.add_trace(
            go.Scatter(
                x=detail.index,
                y=detail[column],
                mode="lines",
                name=column,
                connectgaps=False,
            )
        )
    detail_fig.add_hline(y=100.0, line_dash="dot", opacity=0.45)
    detail_fig.update_layout(
        height=420,
        margin=dict(l=10, r=10, t=20, b=10),
        yaxis_title="Indeks · start = 100",
        xaxis_title=None,
        legend_title=None,
        hovermode="x unified",
    )
    st.plotly_chart(detail_fig, use_container_width=True, config={"displaylogo": False})
else:
    st.caption("Velg minst ett marked for detaljvisning.")

with st.expander("Hvordan lese verktøyet"):
    st.markdown(
        """
- **USD = 100 → 70 målt i gull:** dollaren kjøper 30 % mindre gull enn ved periodens start.
- **S&P = 100 → 85 målt i gull:** S&P har mistet 15 % relativ verdi mot gull, selv om indeksen kan ha steget i dollar.
- **S&P = 100 → 120 målt i gull:** S&P har slått gull med 20 % over perioden.
- Dette er en **alternativ måleenhet**, ikke en påstand om at gull har en matematisk fast «riktig pris».

Verktøyet er laget for å teste hypotesen om at store nominelle bevegelser delvis kan være bevegelser i selve valutaens kjøpekraft, og for å gjøre slike regimeskifter synlige.
        """
    )
