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

NANOSECONDS_PER_HOUR = 3_600_000_000_000


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


def utc_nanoseconds(series: pd.Series) -> pd.Series:
    parsed = pd.to_datetime(series, utc=True, errors="coerce")
    return parsed.map(lambda value: value.value if not pd.isna(value) else pd.NA).astype("Int64")


@st.cache_data(ttl=300)
def fetch_mes(channel: str = CHANNEL) -> pd.DataFrame:
    url = f"https://t.me/s/{channel.lstrip('@')}"
    response = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0 PriceGauger/0.2"})
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

        impact = (
            2.0 * scores["Hormuz/shipping"]
            + 1.5 * scores["Energy"]
            + scores["Escalation"]
            - 0.5 * scores["Diplomacy"]
        )
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
    events["published_at"] = pd.to_datetime(events["published_at"], utc=True, errors="coerce")
    bars["timestamp"] = pd.to_datetime(bars["timestamp"], utc=True, errors="coerce")
    events["join_ns"] = utc_nanoseconds(events["published_at"])
    bars["join_ns"] = utc_nanoseconds(bars["timestamp"])
    events = events.dropna(subset=["published_at", "join_ns"]).copy()
    bars = bars.dropna(subset=["timestamp", "join_ns", "close"]).copy()
    events["join_ns"] = events["join_ns"].astype("int64")
    bars["join_ns"] = bars["join_ns"].astype("int64")
    return (
        events.sort_values("join_ns").reset_index(drop=True),
        bars.sort_values("join_ns").reset_index(drop=True),
    )


def align_events(messages: pd.DataFrame, market: pd.DataFrame, horizon_hours: int) -> pd.DataFrame:
    if messages.empty or market.empty:
        return pd.DataFrame()
    events, bars = prepare_join_data(messages, market)
    if events.empty or bars.empty:
        return pd.DataFrame()

    base = pd.merge_asof(
        events,
        bars.rename(columns={"timestamp": "base_time", "close": "base_close"}),
        on="join_ns",
        direction="forward",
        tolerance=6 * NANOSECONDS_PER_HOUR,
    )
    target_lookup = pd.DataFrame({
        "row_id": range(len(base)),
        "target_join_ns": base["join_ns"] + horizon_hours * NANOSECONDS_PER_HOUR,
    }).sort_values("target_join_ns")
    target = pd.merge_asof(
        target_lookup,
        bars.rename(columns={"join_ns": "target_join_ns", "timestamp": "target_bar", "close": "target_close"}),
        on="target_join_ns",
        direction="forward",
        tolerance=6 * NANOSECONDS_PER_HOUR,
    ).sort_values("row_id")
    base[f"return_{horizon_hours}h_pct"] = (
        target["target_close"].to_numpy() / base["base_close"].to_numpy() - 1
    ) * 100
    return base


def bounded_score(value: float) -> int:
    return int(max(0, min(100, round(value))))


def calculate_pricegauge(messages: pd.DataFrame, market: pd.DataFrame) -> dict[str, int]:
    if messages.empty:
        geo = shipping = energy = 0
    else:
        now = pd.Timestamp.now(tz="UTC")
        recent = messages[pd.to_datetime(messages["published_at"], utc=True) >= now - pd.Timedelta("12h")]
        decay_hours = (now - pd.to_datetime(recent["published_at"], utc=True)).dt.total_seconds() / 3600 if not recent.empty else pd.Series(dtype=float)
        weights = (1 / (1 + decay_hours / 3)) if not recent.empty else pd.Series(dtype=float)
        geo = bounded_score(12 + 14 * float((recent["Escalation"] * weights).sum()) - 8 * float((recent["Diplomacy"] * weights).sum()))
        shipping = bounded_score(8 + 20 * float((recent["Hormuz/shipping"] * weights).sum()))
        energy = bounded_score(8 + 16 * float((recent["Energy"] * weights).sum()))

    momentum = 50
    if not market.empty and len(market) >= 5:
        closes = market["close"].dropna()
        lookback = min(24, len(closes) - 1)
        if lookback > 0 and closes.iloc[-lookback - 1] != 0:
            change = (closes.iloc[-1] / closes.iloc[-lookback - 1] - 1) * 100
            momentum = bounded_score(50 + change * 12)

    total = bounded_score(0.35 * geo + 0.25 * shipping + 0.20 * energy + 0.20 * momentum)
    return {
        "Geopolitisk stress": geo,
        "Hormuz/shipping": shipping,
        "Energiinfrastruktur": energy,
        "Markedsmomentum": momentum,
        "PriceGauge": total,
    }


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
    scores = calculate_pricegauge(messages, market)
    st.subheader("Eksperimentell PriceGauge")
    g1, g2, g3, g4 = st.columns(4)
    g1.metric("TOTAL", scores["PriceGauge"])
    g2.metric("Geopolitikk", scores["Geopolitisk stress"])
    g3.metric("Hormuz", scores["Hormuz/shipping"])
    g4.metric("Momentum", scores["Markedsmomentum"])
    st.progress(scores["PriceGauge"] / 100)
    st.caption("Foreløpig heuristisk score for testing — ikke en validert prognose eller handelsanbefaling.")

    if market.empty:
        st.info("Ingen markedsdata tilgjengelig.")
    else:
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=market["timestamp"], y=market["close"], mode="lines", name=asset_name))
        joined = pd.DataFrame()
        if not messages.empty:
            relevant = messages[messages["impact"] >= min_impact].copy()
            relevant, chart_bars = prepare_join_data(relevant, market)
            if not relevant.empty and not chart_bars.empty:
                joined = pd.merge_asof(
                    relevant,
                    chart_bars,
                    on="join_ns",
                    direction="nearest",
                    tolerance=6 * NANOSECONDS_PER_HOUR,
                ).dropna(subset=["close"])
                if not joined.empty:
                    hover = (
                        joined["published_at"].dt.strftime("%Y-%m-%d %H:%M UTC")
                        + "<br>Impact: " + joined["impact"].round(1).astype(str)
                        + "<br>" + joined["text"].str.slice(0, 220)
                    )
                    fig.add_trace(go.Scatter(
                        x=joined["timestamp"],
                        y=joined["close"],
                        mode="markers",
                        name="MES-hendelse",
                        marker={"size": 11, "symbol": "diamond", "line": {"width": 1}},
                        text=hover,
                        hovertemplate="%{text}<extra></extra>",
                    ))
        fig.update_layout(height=500, margin=dict(l=10, r=10, t=20, b=10), legend_orientation="h")
        st.plotly_chart(fig, use_container_width=True)

        if not joined.empty:
            st.subheader("Undersøk én hendelse")
            event_options = joined.sort_values("published_at", ascending=False).reset_index(drop=True)
            labels = event_options.apply(
                lambda row: f"{row['published_at'].strftime('%d.%m %H:%M')} · impact {row['impact']:.1f} · {row['text'][:65]}",
                axis=1,
            )
            selected_index = st.selectbox("MES-melding", range(len(labels)), format_func=lambda i: labels.iloc[i])
            selected = event_options.iloc[selected_index]
            st.write(selected["text"])
            st.caption(selected["published_at"].strftime("%Y-%m-%d %H:%M UTC"))

            returns = {}
            for hours in (1, 4, 24):
                one_event = messages[messages["url"] == selected["url"]]
                result = align_events(one_event, market, hours)
                col = f"return_{hours}h_pct"
                returns[hours] = result[col].iloc[0] if not result.empty and col in result and pd.notna(result[col].iloc[0]) else None
            r1, r4, r24 = st.columns(3)
            r1.metric("Etter 1 t", "–" if returns[1] is None else f"{returns[1]:+.2f} %")
            r4.metric("Etter 4 t", "–" if returns[4] is None else f"{returns[4]:+.2f} %")
            r24.metric("Etter 24 t", "–" if returns[24] is None else f"{returns[24]:+.2f} %")
            st.link_button("Åpne originalen i Telegram", selected["url"])

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
                rows.append({
                    "Kategori": category,
                    "N": len(subset),
                    "Gj.snitt %": subset[col].mean(),
                    "Median %": subset[col].median(),
                    "Positive %": (subset[col] > 0).mean() * 100,
                })
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