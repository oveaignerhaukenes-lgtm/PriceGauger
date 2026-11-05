"""Live-refreshing RESEARCH dashboard for scheduled US macro-releases.

The Saxo stream writes quotes even when this page is closed. No orders.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from streamlit_autorefresh import st_autorefresh

from database import connect
from instrument_registry_v2 import list_subscribed_sources_v2
from macro_release_lag_observer_v1 import (
    HORIZONS, POST_SECONDS, PRE_SECONDS, market_group,
    paper_followthrough, release_in_capture_window, releases, study_release, utc,
)

st.set_page_config(page_title="Makroslipp · Lead/Lag | PriceGauger", layout="wide")
st.title("Makroslipp · Markedsreaksjon og etterslep")
st.warning(
    "RESEARCH / PAPER – ingen LIVE-handler eller endringer i AutoTrader. "
    "Tidspunktene viser når PriceGauger MOTTOk Saxo-kurser, ikke nødvendigvis "
    "når børsen endret pris. 1 Hz er maks opptaksfrekvens, ikke garantert. "
    "Manglende data, store spreader og faktisk ordreforsinkelse kan "
    "gjøre et tilsynelatende etterslep utnyttbart eller helt verdiløst."
)
st.caption(
    "BLS: NFP 6. november, CPI 10. november, PPI 13. november 2026; "
    "alle kl. 14.30 norsk vintertid (13.30 UTC). "
    "Det registreres 3 minutter før og 15 minutter etter slippet."
)
choices = releases()
selected = st.selectbox(
    "Rapport", choices, index=0,
    format_func=lambda p: f"{p[0]} · {p[1].astimezone().strftime('%d.%m.%Y %H:%M %Z')} "
                           f"({p[1].strftime('%H:%M')} UTC)"
)
kind, event_at = selected
threshold = st.slider("Minste registrerte reaksjon (basispunkter)", 2, 30, 5, 1)
latency = st.select_slider("PAPER: antatt beslutnings-/ordrelatens", (1, 3, 5, 10), value=3)
hold = st.select_slider("PAPER: holdetid (sekunder)", (10, 30, 60, 120, 300), value=60)
now = datetime.now(timezone.utc)
active = release_in_capture_window(now) and (
    event_at - timedelta(seconds=PRE_SECONDS) <= now <= event_at + timedelta(seconds=POST_SECONDS)
)
if active:
    st.info("Aktivt opptaksvindu. Viser nye data automatisk hvert 3. sekund.")
    st_autorefresh(interval=3000, key=f"macro_lag_{kind}")
elif now < event_at - timedelta(seconds=PRE_SECONDS):
    st.info("Rapporten ligger frem i tid; lagret prisreaksjon er ennå ikke tilgjengelig.")
else:
    st.caption("Opptaksvinduet er avsluttet. Historiske data oppdateres ved sideåpning.")

try:
    subscribed = list_subscribed_sources_v2(provider="saxo")
    available = [
        f"{market_group(src.market_name)} · {src.market_name} · UIC {src.provider_instrument_id}"
        for src in subscribed if market_group(src.market_name)
    ]
    st.caption("Abonnerte Saxo-kilder: " + (", ".join(available) if available else "ingen funnet"))
except Exception as exc:
    st.caption(f"Kunne ikke bekrefte abonnementslisten ({type(exc).__name__}).")

try:
    start = event_at - timedelta(seconds=PRE_SECONDS)
    end = event_at + timedelta(seconds=POST_SECONDS)
    with connect() as db:
        rows = [
            dict(row) for row in db.execute(
                """SELECT provider_uic, market_name, quote_at, received_at, bid, ask
                   FROM lsim_hyper_quotes_1s
                   WHERE quote_at>=? AND quote_at<=?
                   ORDER BY quote_at LIMIT 30001""",
                (start.isoformat(), end.isoformat())
            ).fetchall()
        ]
    if len(rows) > 30000:
        raise ValueError("Mer enn 30 000 målinger; begrens datamengden før vurdering.")
except Exception as exc:
    st.error(f"Kunne ikke lese opptaksdata ({type(exc).__name__}).")
    st.stop()

st.metric("Lagrede Saxo BBO-observasjoner i rapportvinduet", len(rows))
if not rows:
    st.info(
        "Foreløpig ingen ettsekunds Saxo-bid/ask i dette tidsvinduet. "
        "Dette er ikke et nullresultat. Dersom gull eller sølv mangler i "
        "abonnementslisten, må de abonneres før NFP for at vi skal kunne måle etterslepet."
    )
    st.stop()

report = study_release(rows, event=event_at, threshold_bps=threshold)
lag = report["tech_minus_gold_first_threshold_seconds"]
if lag is not None:
    st.metric("Tech100 minus gull · første terskelpassering", f"{lag:+.1f} sek")
    st.caption(
        "Deskriptiv differanse i mottakstid mellom egne terskelbrudd; "
        "et positivt tall betyr senere registrert terskelbrudd i Tech100. "
        "Dette er IKKE bevis for at en ordre kunne vært utført før bevegelsen."
    )
else:
    st.info("Ingen pålitelig beregning av gull→Tech100-etterslep ennå. "
            "Kontroller abonnementsdekning, førkurs og datagap.")

table = []
for item in report["markets"]:
    first = item["first_move"]
    table.append({
        "Marked": item["market"], "UIC": item["uic"], "Quotes": item["quotes"],
        "Kvalitet": item["quality"],
        "Gap rundt slipp (s)": item["release_gap_seconds"],
        "Første 5bp+ reaksjon (s)": first["seconds"] if first else None,
        "Retning": first["direction"] if first else None,
        "5s (bp)": item["returns_bps"].get(5),
        "30s (bp)": item["returns_bps"].get(30),
        "60s (bp)": item["returns_bps"].get(60),
        "300s (bp)": item["returns_bps"].get(300),
    })
st.subheader("Første reaksjon og videre bevegelse")
st.dataframe(pd.DataFrame(table), hide_index=True, use_container_width=True)
for group in ("Gull", "Sølv", "Tech100"):
    if not any(item["market"] == group for item in table):
        st.warning(f"{group}: ingen gyldige historiske BBO-observasjoner i rapportvinduet.")

figure = go.Figure()
for item in report["markets"]:
    if item["baseline"] is None:
        continue
    selected_uic = item["uic"]
    points = []
    for r in rows:
        if int(r["provider_uic"]) != selected_uic:
            continue
        try:
            received = utc(r["received_at"])
            quote = utc(r["quote_at"])
            bid, ask = float(r["bid"]), float(r["ask"])
            if bid <= 0 or ask < bid or abs((received-quote).total_seconds()) > 5:
                continue
        except (ValueError, TypeError, OverflowError):
            continue
        elapsed = (received - event_at).total_seconds()
        points.append((elapsed, ((bid+ask)/2 / item["baseline"] - 1) * 10000))
    if points:
        figure.add_trace(go.Scatter(
            x=[p[0] for p in points], y=[p[1] for p in points],
            mode="markers", name=f"{item['market']} UIC {selected_uic}",
            marker={"size": 4},
        ))
figure.add_vline(x=0, line_dash="dash")
figure.update_layout(
    xaxis_title="Sekunder fra publisering (basert på mottakstid)",
    yaxis_title="Endring fra siste førkurs (bp)",
    height=460, margin={"l": 20, "r": 20, "t": 20, "b": 20},
)
st.plotly_chart(figure, use_container_width=True)
st.caption(
    "Punktene er faktiske lagrede observasjoner. Linjer interpoleres ikke. "
    "Forskjellig UIC/produkt holdes separat. Et avvikende datapunkt kan "
    "skyldes spread, ikke bare en mid-price-bevegelse."
)

st.subheader("Kontrafaktisk gullsignal → Tech100 (kun PAPER)")
paper = paper_followthrough(
    rows, event=event_at, threshold_bps=threshold,
    latency_seconds=latency, hold_seconds=hold,
)
if paper["status"] == "PAPER_BBO_PROXY_ONLY":
    a, b, c = st.columns(3)
    a.metric("Signalretning (gull)", paper["signal_direction"])
    b.metric("Tech100 proxy-netto etter spread", f"{paper['net_after_spread_bps']:+.2f} bp")
    c.metric("Antatt ekstra latens", f"{latency} sekunder")
    st.caption(
        "Entry: " + paper["entry_received_at"] +
        " · Exit: " + paper["exit_received_at"] +
        ". Bare bid/ask-proxy. Inkluderer ikke ekstra slippage, kurtasje, finansiering "
        "eller at ordren kan avvises. Ikke estimert LIVE-P/L."
    )
else:
    st.info("PAPER ikke beregnbart: " + paper["status"])

st.download_button(
    "Eksporter rapport som JSON",
    json.dumps({"schema": "MACRO_RELEASE_LAG_RESEARCH_V1",
                "report": report, "paper": paper,
                "quote_count": len(rows)},
               ensure_ascii=False, indent=2, allow_nan=False),
    file_name=f"macro_lag_{kind.lower()}_{event_at:%Y%m%d}.json",
    mime="application/json",
)
