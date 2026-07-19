from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import urlparse

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
from bs4 import BeautifulSoup

from config import twelve_data_api_key
from market_data import MarketRequest, TwelveDataProvider, YahooProvider, fetch_market_data

st.set_page_config(page_title="PriceGauger Alpha", page_icon="📡", layout="wide")

CHANNEL = "Middle_East_Spectator"
NANOSECONDS_PER_HOUR = 3_600_000_000_000

ASSETS = {
    "Brent": {"yahoo": "BZ=F"},
    "Silver": {"twelve": "XAG/USD", "yahoo": "SI=F"},
    "Gold": {"twelve": "XAU/USD", "yahoo": "GC=F"},
    "DXY": {"yahoo": "DX-Y.NYB"},
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


def utc_nanoseconds(series: pd.Series) -> pd.Series:
    parsed = pd.to_datetime(series, utc=True, errors="coerce")
    return parsed.map(lambda value: value.value if not pd.isna(value) else pd.NA).astype("Int64")


def valid_nordnet_url(value: str) -> bool:
    if not value:
        return False
    try:
        parsed = urlparse(value)
        return parsed.scheme in {"http", "https"} and "nordnet" in parsed.netloc.lower()
    except ValueError:
        return False


@st.cache_data(ttl=300)
def fetch_mes(channel: str = CHANNEL) -> pd.DataFrame:
    response = requests.get(
        f"https://t.me/s/{channel.lstrip('@')}",
        timeout=30,
        headers={"User-Agent": "Mozilla/5.0 PriceGauger/0.6"},
    )
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    rows = []
    for wrap in soup.select(".tgme_widget_message_wrap"):
        post = wrap.select_one(".tgme_widget_message")
        time_node = wrap.select_one("time")
        if not post or not time_node or not time_node.get("datetime"):
            continue
        data_post = post.get("data-post", "")
        if "/" not in data_post:
            continue
        channel_name, message_id = data_post.rsplit("/", 1)
        text_node = wrap.select_one(".tgme_widget_message_text")
        views_node = wrap.select_one(".tgme_widget_message_views")
        text = text_node.get_text("\n", strip=True) if text_node else "[Media-only post]"
        lowered = text.lower()
        scores = {
            category: sum(bool(re.search(rf"\b{re.escape(word)}\b", lowered)) for word in words)
            for category, words in KEYWORDS.items()
        }
        impact = 2.0 * scores["Hormuz/shipping"] + 1.5 * scores["Energy"] + scores["Escalation"] - 0.5 * scores["Diplomacy"]
        rows.append({
            "published_at": pd.to_datetime(time_node["datetime"], utc=True),
            "text": text,
            "views": parse_views(views_node.get_text(strip=True) if views_node else None),
            "url": f"https://t.me/{channel_name}/{message_id}",
            "impact": impact,
            **scores,
        })
    return pd.DataFrame(rows).sort_values("published_at", ascending=False) if rows else pd.DataFrame()


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
    return events.sort_values("join_ns").reset_index(drop=True), bars.sort_values("join_ns").reset_index(drop=True)


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
    base[f"return_{horizon_hours}h_pct"] = (target["target_close"].to_numpy() / base["base_close"].to_numpy() - 1) * 100
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
        weights = 1 / (1 + decay_hours / 3) if not recent.empty else pd.Series(dtype=float)
        geo = bounded_score(12 + 14 * float((recent["Escalation"] * weights).sum()) - 8 * float((recent["Diplomacy"] * weights).sum()))
        shipping = bounded_score(8 + 20 * float((recent["Hormuz/shipping"] * weights).sum()))
        energy = bounded_score(8 + 16 * float((recent["Energy"] * weights).sum()))
    momentum = 50
    if not market.empty and len(market) >= 5:
        closes = market["close"].dropna()
        lookback = min(60, len(closes) - 1)
        if lookback > 0 and closes.iloc[-lookback - 1] != 0:
            momentum = bounded_score(50 + ((closes.iloc[-1] / closes.iloc[-lookback - 1] - 1) * 100) * 12)
    total = bounded_score(0.35 * geo + 0.25 * shipping + 0.20 * energy + 0.20 * momentum)
    return {"Geopolitisk stress": geo, "Hormuz/shipping": shipping, "Energiinfrastruktur": energy, "Markedsmomentum": momentum, "PriceGauge": total}


st.title("📡 PriceGauger Alpha")
st.caption("Hendelser, markedsdata og historiske reaksjoner i en modulær analysearkitektur")

with st.sidebar:
    st.header("Innstillinger")
    asset_name = st.selectbox("Marked", list(ASSETS))
    interval = st.selectbox("Intervall", ["5min", "15min", "30min", "1h"], index=0)
    outputsize = st.selectbox("Antall prisbarer", [500, 1000, 2000, 5000], index=1)
    provider_choice = st.selectbox("Prisleverandør", ["Automatisk", "Twelve Data", "Yahoo Finance"])
    min_impact = st.slider("Minste impact-score", -2.0, 10.0, 0.0, 0.5)
    nordnet_url = st.text_input("Nordnet-produkt", placeholder="Lim inn produktlenken")
    if nordnet_url and not valid_nordnet_url(nordnet_url):
        st.warning("Lenken ser ikke ut som en Nordnet-lenke.")
    if valid_nordnet_url(nordnet_url):
        st.link_button("Åpne Nordnet-produkt", nordnet_url, use_container_width=True)
    if st.button("Oppdater data", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

try:
    messages = fetch_mes()
except Exception as exc:
    st.error(f"Kunne ikke hente MES: {exc}")
    messages = pd.DataFrame()

request = MarketRequest(asset_name=asset_name, interval=interval, outputsize=outputsize, symbols=ASSETS[asset_name])
all_providers = [TwelveDataProvider(twelve_data_api_key()), YahooProvider()]
if provider_choice == "Twelve Data":
    providers = [all_providers[0]]
elif provider_choice == "Yahoo Finance":
    providers = [all_providers[1]]
else:
    providers = all_providers

try:
    result = fetch_market_data(request, providers)
    market = result.frame
    feed_name = result.provider_name
except Exception as exc:
    st.error(f"Kunne ikke hente markedsdata: {exc}")
    market = pd.DataFrame()
    feed_name = "Ingen"

m1, m2, m3, m4 = st.columns(4)
m1.metric("MES-meldinger", len(messages))
m2.metric("Prisbarer", len(market))
m3.metric("Datakilde", feed_name)
m4.metric("Sist oppdatert", datetime.now(timezone.utc).strftime("%H:%M UTC"))

chart_tab, events_tab, test_tab, risk_tab, lab_tab = st.tabs([
    "Dashboard", "Hendelser", "Historisk test", "Risiko", "Historical Event Lab"
])

with chart_tab:
    scores = calculate_pricegauge(messages, market)
    st.subheader("Eksperimentell PriceGauge")
    g1, g2, g3, g4 = st.columns(4)
    g1.metric("TOTAL", scores["PriceGauge"])
    g2.metric("Geopolitikk", scores["Geopolitisk stress"])
    g3.metric("Hormuz", scores["Hormuz/shipping"])
    g4.metric("Momentum", scores["Markedsmomentum"])
    st.progress(scores["PriceGauge"] / 100)

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
                joined = pd.merge_asof(relevant, chart_bars, on="join_ns", direction="nearest", tolerance=6 * NANOSECONDS_PER_HOUR).dropna(subset=["close"])
                if not joined.empty:
                    hover = joined["published_at"].dt.strftime("%Y-%m-%d %H:%M UTC") + "<br>Impact: " + joined["impact"].round(1).astype(str) + "<br>" + joined["text"].str.slice(0, 220)
                    fig.add_trace(go.Scatter(x=joined["timestamp"], y=joined["close"], mode="markers", name="MES-hendelse", marker={"size": 11, "symbol": "diamond", "line": {"width": 1}}, text=hover, hovertemplate="%{text}<extra></extra>"))
        fig.update_layout(height=500, margin=dict(l=10, r=10, t=20, b=10), legend_orientation="h", dragmode=False)
        st.plotly_chart(fig, use_container_width=True, config={"scrollZoom": False, "displayModeBar": True, "doubleClick": "reset", "responsive": True})
        st.caption("Én finger scroller siden. Bruk verktøylinjen i grafen for zoom/panoreringsmodus.")

        if not joined.empty:
            st.subheader("Undersøk én hendelse")
            event_options = joined.sort_values("published_at", ascending=False).reset_index(drop=True)
            labels = event_options.apply(lambda row: f"{row['published_at'].strftime('%d.%m %H:%M')} · impact {row['impact']:.1f} · {row['text'][:65]}", axis=1)
            selected_index = st.selectbox("MES-melding", range(len(labels)), format_func=lambda i: labels.iloc[i])
            selected = event_options.iloc[selected_index]
            st.write(selected["text"])
            st.caption(selected["published_at"].strftime("%Y-%m-%d %H:%M UTC"))
            returns = {}
            for hours in (1, 4, 24):
                aligned_one = align_events(messages[messages["url"] == selected["url"]], market, hours)
                col = f"return_{hours}h_pct"
                returns[hours] = aligned_one[col].iloc[0] if not aligned_one.empty and col in aligned_one and pd.notna(aligned_one[col].iloc[0]) else None
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
    horizon = st.selectbox("Reaksjonsvindu", [1, 4, 24], index=1)
    aligned = align_events(messages, market, horizon)
    col = f"return_{horizon}h_pct"
    valid = aligned.dropna(subset=[col]) if not aligned.empty and col in aligned else pd.DataFrame()
    if valid.empty:
        st.info("Ingen tidsmessig overlapp mellom meldingene og prisdataene ennå.")
    else:
        a, b, c = st.columns(3)
        a.metric("Matcher", len(valid))
        b.metric("Gjennomsnitt", f"{valid[col].mean():.2f} %")
        c.metric("Andel positive", f"{(valid[col] > 0).mean() * 100:.0f} %")

with risk_tab:
    capital = st.number_input("Kapital (NOK)", min_value=1000.0, value=20000.0, step=1000.0)
    risk_pct = st.slider("Maks risiko per handel (%)", 0.1, 3.0, 0.5, 0.1)
    stop_pct = st.slider("Stop-avstand i underliggende (%)", 0.1, 10.0, 1.5, 0.1)
    leverage = st.slider("Gearing", 1.0, 25.0, 5.0, 0.5)
    roundtrip_cost_pct = st.number_input("Anslått spread + slippage tur/retur (%)", min_value=0.0, value=0.4, step=0.1)
    max_loss = capital * risk_pct / 100
    product_amount = max_loss / ((stop_pct / 100) * leverage)
    estimated_cost = product_amount * roundtrip_cost_pct / 100
    r1, r2, r3 = st.columns(3)
    r1.metric("Maks tap", f"{max_loss:,.0f} NOK")
    r2.metric("Produktbeløp", f"{product_amount:,.0f} NOK")
    r3.metric("Estimert handelskostnad", f"{estimated_cost:,.0f} NOK")
    st.caption("Neste steg er å lese faktisk Nordnet-produktpris og beregne realisert nettoresultat per signal.")

with lab_tab:
    st.subheader("Historical Event Lab")
    st.write("Her henter og lagrer vi strukturerte GDELT-hendelser før AI får et begrenset og etterprøvbart datasett å resonnere over.")
    st.page_link("pages/1_Historical_Event_Lab.py", label="Åpne Historical Event Lab", icon="🧭", use_container_width=True)
    st.caption("GDELT er hendelsesdatakilden. Prisleverandøren over er separat og kan byttes uavhengig.")
