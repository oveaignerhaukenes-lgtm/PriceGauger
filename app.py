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
from decision_engine import build_market_assessment, build_strategy_suggestion
from decision_trace import build_decision_trace, save_decision_trace
from event_dna import build_event_dna, build_market_profile, find_similar_events
from event_lab_ui import render_event_lab
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
        headers={"User-Agent": "Mozilla/5.0 PriceGauger/0.9"},
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
        impact = (
            2.0 * scores["Hormuz/shipping"]
            + 1.5 * scores["Energy"]
            + scores["Escalation"]
            - 0.5 * scores["Diplomacy"]
        )
        rows.append(
            {
                "published_at": pd.to_datetime(time_node["datetime"], utc=True),
                "text": text,
                "views": parse_views(views_node.get_text(strip=True) if views_node else None),
                "url": f"https://t.me/{channel_name}/{message_id}",
                "impact": impact,
                **scores,
            }
        )
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
    return events.sort_values("join_ns"), bars.sort_values("join_ns")


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
    lookup = pd.DataFrame(
        {"row_id": range(len(base)), "target_join_ns": base["join_ns"] + horizon_hours * NANOSECONDS_PER_HOUR}
    ).sort_values("target_join_ns")
    target = pd.merge_asof(
        lookup,
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
        decay = (
            (now - pd.to_datetime(recent["published_at"], utc=True)).dt.total_seconds() / 3600
            if not recent.empty
            else pd.Series(dtype=float)
        )
        weights = 1 / (1 + decay / 3) if not recent.empty else pd.Series(dtype=float)
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
    return {
        "Geopolitisk stress": geo,
        "Hormuz/shipping": shipping,
        "Energiinfrastruktur": energy,
        "Markedsmomentum": momentum,
        "PriceGauge": total,
    }


st.title("📡 PriceGauger Alpha")
st.caption("Hendelser, markedsdata og historiske reaksjoner i en modulær analysearkitektur")

with st.sidebar:
    st.header("Innstillinger")
    asset_name = st.selectbox("Marked", list(ASSETS))
    interval = st.selectbox("Intervall", ["5min", "15min", "30min", "1h"], index=0)
    outputsize = st.selectbox("Antall prisbarer", [500, 1000, 2000, 5000], index=1)
    provider_choice = st.selectbox("Prisleverandør", ["Automatisk", "Twelve Data", "Yahoo Finance"])
    min_impact = st.slider("Minste impact-score", -2.0, 10.0, 0.0, 0.5)
    profit_capture = st.slider("Andel av forventet bevegelse til autosalg", 0.50, 1.00, 0.80, 0.05)
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
providers = [all_providers[0]] if provider_choice == "Twelve Data" else [all_providers[1]] if provider_choice == "Yahoo Finance" else all_providers
try:
    market_result = fetch_market_data(request, providers)
    market = market_result.frame
    feed_name = market_result.provider_name
except Exception as exc:
    st.error(f"Kunne ikke hente markedsdata: {exc}")
    market = pd.DataFrame()
    feed_name = "Ingen"

m1, m2, m3, m4 = st.columns(4)
m1.metric("MES-meldinger", len(messages))
m2.metric("Prisbarer", len(market))
m3.metric("Datakilde", feed_name)
m4.metric("Sist oppdatert", datetime.now(timezone.utc).strftime("%H:%M UTC"))

chart_tab, events_tab, test_tab, risk_tab, decision_tab, lab_tab = st.tabs(
    ["Dashboard", "Hendelser", "Historisk test", "Risiko", "Beslutningslab", "Historical Event Lab"]
)

with chart_tab:
    scores = calculate_pricegauge(messages, market)
    st.subheader("Eksperimentell PriceGauge")
    g1, g2, g3, g4 = st.columns(4)
    g1.metric("TOTAL", scores["PriceGauge"])
    g2.metric("Geopolitikk", scores["Geopolitisk stress"])
    g3.metric("Hormuz", scores["Hormuz/shipping"])
    g4.metric("Momentum", scores["Markedsmomentum"])
    st.progress(scores["PriceGauge"] / 100)

    historical_intraday = st.session_state.get("gdelt_intraday_reactions", [])
    assessment = build_market_assessment(
        asset=asset_name,
        messages=messages,
        market=market,
        intraday_reactions=historical_intraday,
    )
    strategy = build_strategy_suggestion(assessment, profit_capture=profit_capture)

    st.subheader("V1 beslutningsoutput")
    st.caption("Analysegrunnlaget og handlingsregelen vises separat, slik at de kan evalueres uavhengig.")
    with st.container(border=True):
        st.markdown("### 1. Analyse")
        a1, a2, a3, a4 = st.columns(4)
        a1.metric("Retning", assessment.direction)
        a2.metric("Konfidens", f"{assessment.confidence_pct:.1f} %")
        a3.metric(
            "Forventet bevegelse",
            f"{assessment.expected_move_pct:+.3f} %" if assessment.expected_move_pct is not None else "Mangler historikk",
        )
        a4.metric("Tidshorisont", assessment.horizon)
        st.write(f"**Evidensgrad:** {assessment.evidence_grade} · **Historisk utvalg:** {assessment.historical_sample}")
        for reason in assessment.rationale:
            st.write(f"• {reason}")

    with st.container(border=True):
        st.markdown("### 2. Metodisk handlingsforslag")
        s1, s2, s3, s4 = st.columns(4)
        s1.metric("Handling", strategy.action)
        s2.metric("Maks gearing", f"{strategy.max_leverage:.1f}×")
        s3.metric(
            "Autosalg",
            f"{strategy.take_profit_pct:.3f} %" if strategy.take_profit_pct is not None else "—",
        )
        s4.metric(
            "Stop i underliggende",
            f"{strategy.stop_loss_pct:.3f} %" if strategy.stop_loss_pct is not None else "—",
        )
        st.write(strategy.methodology)
        st.warning(strategy.warning)

    if market.empty:
        st.info("Ingen markedsdata tilgjengelig.")
    else:
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=market["timestamp"], y=market["close"], mode="lines", name=asset_name))
        fig.update_layout(height=500, margin=dict(l=10, r=10, t=20, b=10), legend_orientation="h")
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
    max_loss = capital * risk_pct / 100
    product_amount = max_loss / ((stop_pct / 100) * leverage)
    r1, r2 = st.columns(2)
    r1.metric("Maks tap", f"{max_loss:,.0f} NOK")
    r2.metric("Produktbeløp", f"{product_amount:,.0f} NOK")

with decision_tab:
    st.subheader("EventDNA og historisk beslutningsgrunnlag")
    events = st.session_state.get("gdelt_events", [])
    reactions = st.session_state.get("gdelt_intraday_reactions", [])

    if not events:
        st.info("Hent hendelser i Historical Event Lab først. Deretter blir EventDNA og historiske matcher tilgjengelige her.")
    else:
        event_options = {
            f"{getattr(event, 'event_date', '')} · {getattr(event, 'title', '')[:110]}": index
            for index, event in enumerate(events)
        }
        selected_label = st.selectbox("Velg hendelse", list(event_options), key="decision_event")
        selected_event = events[event_options[selected_label]]
        dna = build_event_dna(selected_event)
        matches = find_similar_events(selected_event, events, limit=20, minimum_score=0.0)
        profile = build_market_profile(asset=asset_name, similar_events=matches, reactions=reactions)

        d1, d2, d3, d4 = st.columns(4)
        d1.metric("Hendelsestype", dna.event_type)
        d2.metric("Mål", dna.target)
        d3.metric("Alvorlighet", f"{dna.severity:.0%}")
        d4.metric("Kildekvalitet", f"{dna.source_quality:.0%}")

        with st.expander("Se komplett EventDNA"):
            st.json(dna.to_record())

        st.markdown("### Lignende historiske hendelser")
        if not matches:
            st.info("Ingen andre hendelser finnes i det innlastede datasettet.")
        else:
            match_rows = [
                {
                    "Likhet": item.score,
                    "Dato": item.event.event_date,
                    "Hendelse": item.event.title,
                    "Land": item.event.country,
                    "Type": item.dna.event_type,
                    "Mål": item.dna.target,
                }
                for item in matches
            ]
            st.dataframe(
                pd.DataFrame(match_rows),
                use_container_width=True,
                hide_index=True,
                column_config={"Likhet": st.column_config.ProgressColumn("Likhet", min_value=0.0, max_value=1.0)},
            )

        st.markdown(f"### Market Profile · {asset_name}")
        p1, p2, p3, p4 = st.columns(4)
        p1.metric("Retning", profile.direction)
        p2.metric("Konfidens", f"{profile.confidence_pct:.1f} %")
        p3.metric("Utvalg", profile.sample_size)
        p4.metric(
            "Median +4t",
            f"{profile.median_4h_pct:+.3f} %" if profile.median_4h_pct is not None else "Mangler data",
        )
        st.caption(
            f"Effektivt utvalg {profile.effective_sample_size:.2f} · "
            f"Andel positive 1t: {profile.positive_share_pct:.1f} %"
            if profile.positive_share_pct is not None
            else f"Effektivt utvalg {profile.effective_sample_size:.2f} · Ingen 1t-observasjoner"
        )

        trace = build_decision_trace(
            event=selected_event,
            event_dna=dna,
            similar_events=matches,
            market_profile=profile,
            assessment=assessment,
            strategy=strategy,
        )
        with st.expander("Decision Trace"):
            st.json(trace.to_record())
        if st.button("Lagre Decision Trace", type="primary", use_container_width=True):
            save_decision_trace(trace)
            st.session_state.last_decision_trace_id = trace.trace_id
            st.success(f"Beslutningssporet er lagret: {trace.trace_id}")

with lab_tab:
    render_event_lab()
