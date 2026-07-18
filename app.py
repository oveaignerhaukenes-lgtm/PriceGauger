from __future__ import annotations

import re
from datetime import datetime, timezone

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
import yfinance as yf
from bs4 import BeautifulSoup

st.set_page_config(page_title="PriceGauger Alpha", page_icon="📡", layout="wide")

CHANNEL = "Middle_East_Spectator"
ASSETS = {
    "Brent": "BZ=F",
    "Silver": "SI=F",
    "Gold": "GC=F",
    "DXY": "DX-Y.NYB",
}

KEYWORDS = {
    "Hormuz/shipping": ["hormuz", "tanker", "shipping", "vessel", "strait", "port", "naval", "mine"],
    "Energy": ["oil", "gas", "refinery", "pipeline", "terminal", "aramco", "lng", "production"],
    "Escalation": ["attack", "strike", "missile", "drone", "bomb", "war", "airstrike", "explosion"],
    "Diplomacy": ["ceasefire", "negotiation", "talks", "deal", "agreement", "truce", "mediation"],
}


def parse_views(raw: str | None) -> int | None:
    if not raw:
        return None
    match = re.match(r"([\d.,]+)\s*([KM]?)", raw.strip().upper())
    if not match:
        return None
    value = float(match.group(1).replace(",", "."))
    if match.group(2) == "K":
        value *= 1_000
    elif match.group(2) == "M":
        value *= 1_000_000
    return int(value)


def normalise_join_time(series: pd.Series) -> pd.Series:
    """Return one consistent timezone-naive UTC dtype for pandas merge_asof."""
    return pd.to_datetime(series, utc=True, errors="coerce").dt.tz_convert(None)


@st.cache_data(ttl=300)
def fetch_mes(channel: str = CHANNEL) -> pd.DataFrame:
    url = f"https://t.me/s/{channel.lstrip('@')}"
    response = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0 PriceGauger/0.1"})
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    rows = []

    for wrap in soup.select(".tgme_widget_message_wrap"):
        post = wrap.select_one(".tgme_widget_message")
        if not post:
            continue
        data_post = post.get("data-post", "")
        if "/" not in data_post:
            continue
        channel_name, message_id = data_post.rsplit("/", 1)
        time_node = wrap.select_one("time")
        if not time_node or not time_node.get("datetime"):
            continue
        text_node = wrap.select_one(".tgme_widget_message_text")
        views_node = wrap.select_one(".tgme_widget_message_views")
        text = text_node.get_text("\n", strip=True) if text_node else "[Media-only post]"
        published = pd.to_datetime(time_node["datetime"], utc=True)

        scores = {}
        lowered = text.lower()
        for category, words in KEYWORDS.items():
            scores[category] = sum(bool(re.search(rf"\b{re.escape(word)}\b", lowered)) for word in words)

        impact = 2.0 * scores["Hormuz/shipping"] + 1.5 * scores["Energy"] + scores["Escalation"] - 0.5 * scores["Diplomacy"]
        rows.append({
            "published_at": published,
            "text": text,
            "views": parse_views(views_node.get_text(strip=True) if views_node else None),
            "url": f"https://t.me/{channel_name}/{message_id}",
            "impact": impact,
            **scores,
        })

    return pd.DataFrame(rows).sort_values("published_at", ascending=False) if rows else pd.DataFrame()


@st.cache_data(ttl=300)
def fetch_market(symbol: str, period: str = "30d", interval: str = "1h") -> pd.DataFrame:
    frame = yf.download(symbol, period=period, interval=interval, auto_adjust=False, progress=False, threads=False)
    if frame.empty:
        return frame
    if isinstance(frame.columns, pd.MultiIndex):
        frame.columns = frame.columns.get_level_values(0)
    frame = frame.reset_index()
    time_col = "Datetime" if "Datetime" in frame.columns else "Date"
    frame[time_col] = pd.to_datetime(frame[time_col], utc=True, errors="coerce")
    frame = frame.rename(columns={time_col: "timestamp", "Close": "close"})
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    return frame.dropna(subset=["timestamp", "close"])


def prepare_join_data(messages: pd.DataFrame, market: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    events = messages.copy()
    bars = market[["timestamp", "close"]].copy()
    events["published_at"] = normalise_join_time(events["published_at"])
    bars["timestamp"] = normalise_join_time(bars["timestamp"])
    events = events.dropna(subset=["published_at"]).sort_values("published_at").reset_index(drop=True)
    bars = bars.dropna(subset=["timestamp", "close"]).sort_values("timestamp").reset_index(drop=True)
    return events, bars


def align_events(messages: pd.DataFrame, market: pd.DataFrame, horizon_hours: int) -> pd.DataFrame:
    if messages.empty or market.empty:
        return pd.DataFrame()
    events, bars = prepare_join_data(messages, market)
    if events.empty or bars.empty:
        return pd.DataFrame()

    base = pd.merge_asof(
        events,
        bars.rename(columns={"timestamp": "base_time", "close": "base_close"}),
        left_on="published_at",
        right_on="base_time",
        direction="forward",
        tolerance=pd.Timedelta("6h"),
    )
    target_lookup = pd.DataFrame({
        "row_id": range(len(base)),
        "target_time": base["published_at"] + pd.Timedelta(hours=horizon_hours),
    }).sort_values("target_time")
    target = pd.merge_asof(
        target_lookup,
        bars.rename(columns={"timestamp": "target_bar", "close": "target_close"}),
        left_on="target_time",
        right_on="target_bar",
        direction="forward",
        tolerance=pd.Timedelta("6h"),
    ).sort_values("row_id")
    base[f"return_{horizon_hours}h_pct"] = (
        target["target_close"].to_numpy() / base["base_close"].to_numpy() - 1
    ) * 100
    return base


st.title("📡 PriceGauger Alpha")
st.caption("MES-hendelser koblet mot Brent, sølv, gull og DXY")

with st.sidebar:
    st.header("Innstillinger")
    asset_name = st.selectbox("Marked", list(ASSETS))
    interval = st.selectbox("Intervall", ["1h", "30m", "15m", "5m"])
    period = st.selectbox("Historikk", ["7d", "30d", "60d"])
    horizon = st.selectbox("Reaksjonsvindu", [1, 4, 24], index=1)
    min_impact = st.slider("Minste impact-score", -2.0, 10.0, 0.0, 0.5)
    if st.button("Oppdater data", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

try:
    messages = fetch_mes()
except Exception as exc:
    st.error(f"Kunne ikke hente MES: {exc}")
    messages = pd.DataFrame()

try:
    market = fetch_market(ASSETS[asset_name], period=period, interval=interval)
except Exception as exc:
    st.error(f"Kunne ikke hente markedsdata: {exc}")
    market = pd.DataFrame()

m1, m2, m3 = st.columns(3)
m1.metric("MES-meldinger", len(messages))
m2.metric("Prisbarer", len(market))
m3.metric("Sist oppdatert", datetime.now(timezone.utc).strftime("%H:%M UTC"))

chart_tab, events_tab, test_tab, risk_tab = st.tabs(["Dashboard", "Hendelser", "Historisk test", "Risiko"])

with chart_tab:
    if market.empty:
        st.info("Ingen markedsdata tilgjengelig.")
    else:
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=market["timestamp"], y=market["close"], mode="lines", name=asset_name))
        if not messages.empty:
            relevant = messages[messages["impact"] >= min_impact].copy()
            relevant, chart_bars = prepare_join_data(relevant, market)
            if not relevant.empty and not chart_bars.empty:
                joined = pd.merge_asof(
                    relevant,
                    chart_bars,
                    left_on="published_at",
                    right_on="timestamp",
                    direction="nearest",
                    tolerance=pd.Timedelta("6h"),
                ).dropna(subset=["close"])
                if not joined.empty:
                    fig.add_trace(go.Scatter(
                        x=joined["timestamp"],
                        y=joined["close"],
                        mode="markers",
                        name="MES",
                        text=joined["text"].str.slice(0, 180),
                        hovertemplate="%{text}<extra></extra>",
                    ))
        fig.update_layout(height=460, margin=dict(l=10, r=10, t=20, b=10), legend_orientation="h")
        st.plotly_chart(fig, use_container_width=True)

with events_tab:
    if messages.empty:
        st.info("Ingen MES-meldinger tilgjengelig.")
    else:
        for _, row in messages[messages["impact"] >= min_impact].head(100).iterrows():
            with st.container(border=True):
                st.markdown(f"**{row['published_at'].strftime('%Y-%m-%d %H:%M UTC')}**")
                st.write(row["text"])
                st.caption(f"Impact {row['impact']:.1f} · Visninger {row['views'] or 'ukjent'}")
                st.link_button("Åpne i Telegram", row["url"])

with test_tab:
    try:
        aligned = align_events(messages, market, horizon)
    except Exception as exc:
        st.error(f"Kunne ikke koble hendelser og prisdata: {exc}")
        aligned = pd.DataFrame()
    col = f"return_{horizon}h_pct"
    valid = aligned.dropna(subset=[col]) if not aligned.empty and col in aligned else pd.DataFrame()
    if valid.empty:
        st.info("Ingen tidsmessig overlapp mellom meldingene og prisdataene ennå.")
    else:
        a, b, c = st.columns(3)
        a.metric("Matcher", len(valid))
        b.metric("Gjennomsnitt", f"{valid[col].mean():.2f} %")
        c.metric("Andel positive", f"{(valid[col] > 0).mean() * 100:.0f} %")
        rows = []
        for category in KEYWORDS:
            subset = valid[valid[category] > 0]
            if len(subset):
                rows.append({"Kategori": category, "N": len(subset), "Gj.snitt %": subset[col].mean(), "Median %": subset[col].median(), "Positive %": (subset[col] > 0).mean() * 100})
        if rows:
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        st.caption("Dette er deskriptiv korrelasjon, ikke en validert prognose.")

with risk_tab:
    capital = st.number_input("Kapital (NOK)", min_value=1000.0, value=20000.0, step=1000.0)
    risk_pct = st.slider("Maks risiko per handel (%)", 0.1, 3.0, 0.5, 0.1)
    stop_pct = st.slider("Stop-avstand i underliggende (%)", 0.1, 10.0, 1.5, 0.1)
    leverage = st.slider("Gearing", 1.0, 25.0, 5.0, 0.5)
    max_loss = capital * risk_pct / 100
    product_amount = max_loss / ((stop_pct / 100) * leverage)
    r1, r2 = st.columns(2)
    r1.metric("Maks tap", f"{max_loss:,.0f} NOK")
    r2.metric("Omtrentlig produktbeløp", f"{product_amount:,.0f} NOK")
    st.caption("Forenklet beregning: spread, gap, finansiering og endret gearing nær knock-out er ikke inkludert.")