"""Manual read-only four-channel TECH100 data connectivity research.

Saxo GET probes require explicit button clicks; no orders, AI or V3 access.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone

import streamlit as st

from build_info import render_build_badge
from instrument_registry_v2 import list_subscribed_sources_v2
from saxo_provider import configured_client
from storage import DB_PATH
from tech100_four_channel_synthesis_v1 import (
    CHANNELS, IMPULSE, MACRO_NEWS, REGIME, TECH_NEWS, synthesize,
)
from tech100_synthesis_data_v1 import (
    PRICE_CHANNELS, aligned_price_moves, load_archived_gdelt_news,
    load_archived_news, load_archived_yield_snapshot, load_canonical_prices,
    source_candidates, yield_feed_status,
)
from tech100_treasury_source_probe_v1 import (
    TENOR_TERMS, probe_treasury_quote, search_treasury_candidates,
)


LABELS = {
    REGIME: "1 · Makroregime (gull, Brent, DXY, 2/10/30Y)",
    IMPULSE: "2 · Kryssmarkedsimpuls (gull, Brent, DXY, renter)",
    TECH_NEWS: "3 · Teknologinyheter",
    MACRO_NEWS: "4 · Makronyheter",
}

st.set_page_config(page_title="Tech100 · Syntese | PriceGauger", layout="wide")
render_build_badge()
st.title("Tech100 · Syntese")
st.warning(
    "RESEARCH / bare lesing. Moduler og syntese er IKKE koblet til AutoTrader, "
    "Saxo, kontoer eller ordre. Ingen bakgrunns-AI. "
    "Datatilgang er ikke det samme som et validert retningssignal."
)
st.caption(
    "Fire uavhengig valgbare moduler → felles syntese → framtidig kontekstfilter "
    "eller selvstendig impulsinstans. Denne siden leser kun lagrede mottatte data."
)

with st.expander("Undersøk Saxos 2Y / 10Y / 30Y-instrumenter (manuelle GET-kall)"):
    st.caption(
        "Søker kun etter instrumenter og leser en valgt pris på knappeklikk. "
        "Ingen ordre, nye datastrømmer eller bakgrunnskall. Futures-/CFD-kurser "
        "er prisproksyer, ikke faktiske statsrenter i basispunkter."
    )
    if st.button("Søk instrumentkatalogen for 2Y / 10Y / 30Y"):
        try:
            client = configured_client()
            if client is None:
                raise RuntimeError("Saxo access token unavailable")
            st.session_state["tech100_treasury_candidates"] = search_treasury_candidates(client)
            st.session_state.pop("tech100_treasury_quote", None)
        except Exception as exc:
            st.warning(f"Saxo-katalog ikke tilgjengelig ({type(exc).__name__}).")
    available_treasuries = st.session_state.get("tech100_treasury_candidates")
    if available_treasuries is not None:
        st.dataframe([
            {"Løpetidsgruppe": tenor, "Kandidater": len(items)}
            for tenor, items in available_treasuries.items()
        ], hide_index=True, use_container_width=True)
        tenor = st.selectbox("Løpetidsgruppe", tuple(TENOR_TERMS), key="tech100_treasury_tenor")
        tenor_candidates = available_treasuries.get(tenor, ())
        candidate = st.selectbox(
            "Saxo-instrument (eksakt UIC)", tenor_candidates,
            format_func=lambda item: (
                f"{item.symbol} · {item.description} · {item.asset_type} · "
                f"UIC {item.uic} · utløp {item.expiry or 'ukjent'}"
            ),
            disabled=not tenor_candidates,
        ) if tenor_candidates else None
        if candidate is not None and st.button("Les én quote/yield fra Saxo"):
            try:
                client = configured_client()
                if client is None:
                    raise RuntimeError("Saxo access token unavailable")
                st.session_state["tech100_treasury_quote"] = probe_treasury_quote(client, candidate)
            except Exception as exc:
                st.warning(f"Saxo-quote ikke tilgjengelig ({type(exc).__name__}).")
        last_quote = st.session_state.get("tech100_treasury_quote")
        if last_quote is not None and last_quote.candidate == candidate:
            st.dataframe([{
                "Løpetid": last_quote.candidate.tenor_hint,
                "UIC": last_quote.candidate.uic,
                "Type": last_quote.candidate.asset_type,
                "Status": last_quote.status,
                "Kilde sist oppdatert": str(last_quote.source_updated_at or "UKJENT"),
                "Forsinkelse (min)": last_quote.delayed_by_minutes,
                "Bid": last_quote.bid, "Ask": last_quote.ask,
                "BidYield (Saxo råverdi)": last_quote.bid_yield_raw,
                "AskYield (Saxo råverdi)": last_quote.ask_yield_raw,
                "Forklaring": last_quote.detail,
            }], hide_index=True, use_container_width=True)
            st.caption(
                "Én vellykket avlesning bekrefter ikke hyppighet. Flere beviselig "
                "tidsstemplede avlesninger og sammenligning mot faktiske markedsbevegelser "
                "kreves før kilden kan inngå i impulsmodellen."
            )

try:
    subscribed = list_subscribed_sources_v2(provider="saxo")
    candidates = source_candidates(subscribed)
    subscription_issue = None
except Exception as exc:
    subscribed, candidates = (), {key: () for key in PRICE_CHANNELS}
    subscription_issue = type(exc).__name__


def _source_label(item):
    return f"{item.market_name} · {item.display_name} · Saxo UIC {item.provider_instrument_id}"


with st.form("synthesis_read_only_form"):
    selected = st.multiselect(
        "Aktive forskningsmoduler", CHANNELS, default=CHANNELS,
        format_func=lambda item: LABELS[item],
        help="Velg én modul eller alle. Ingen valg endrer handelsinnstillinger.",
    )
    horizon = st.selectbox("Felles horisont for framtidig modell (min)", (5, 15, 60, 240), index=0)
    lookback = st.selectbox("Historisk 1m-prisendring (min)", (5, 15, 30, 60), index=1)
    chosen_uics = {}
    if any(module in selected for module in (REGIME, IMPULSE)):
        st.markdown("**Eksakte Saxo-instrumenter**")
        for name in PRICE_CHANNELS:
            choices = candidates[name]
            chosen = st.selectbox(
                name, options=choices, format_func=_source_label,
                disabled=not choices, help="Kun faktisk abonnerte Saxo-UIC-er.",
            ) if choices else None
            if chosen is not None:
                chosen_uics[name] = chosen.provider_instrument_id
    read = st.form_submit_button("Les lagrede kilder (ingen handel)", type="primary")

if not read:
    st.info("Velg modulene og trykk «Les lagrede kilder» for en tidsstemplet status.")
    st.stop()
if not selected:
    st.warning("Velg minst én modul.")
    st.stop()

now = datetime.now(timezone.utc)
st.caption("Beslutningstid: " + now.strftime("%Y-%m-%d %H:%M:%S UTC"))
rows = []
news_items = ()

if REGIME in selected or IMPULSE in selected:
    price_status = "INGEN PRISDATA"
    price_detail = "Ingen verifiserte og sammenhengende 1m-serier."
    if subscription_issue:
        price_detail = f"Abonnementsregisteret utilgjengelig ({subscription_issue})."
    elif len(chosen_uics) != len(PRICE_CHANNELS):
        price_detail = "Mangler abonnerte UIC-er for Tech100, gull, Brent eller DXY."
    else:
        try:
            windows = load_canonical_prices(
                at=now, lookback_minutes=lookback, subscriptions=subscribed,
                selected_uics=chosen_uics,
            )
            moves = aligned_price_moves(windows, at=now, lookback_minutes=lookback)
            price_status = moves.status
            if moves.status == "VALID":
                price_detail = ", ".join(
                    f"{name} {moves.returns_pct[name]:+.3f}% (UIC {moves.source_ids[name]})"
                    for name in PRICE_CHANNELS
                )
            else:
                price_detail = moves.reason
        except Exception as exc:
            price_status = "UTILGJENGELIG"
            price_detail = f"Feil ved lesing av kanoniske barer: {type(exc).__name__}"

    try:
        yield_snapshot = load_archived_yield_snapshot(at=now)
        yields = yield_feed_status(yield_snapshot, at=now)
        yield_detail = ", ".join(f"{item.tenor}={item.status}" for item in yields)
    except Exception as exc:
        yield_detail = f"Ingen verifiserbar rentekilde ({type(exc).__name__})"

    for module in (REGIME, IMPULSE):
        if module in selected:
            rows.append({
                "Modul": LABELS[module],
                "Data": price_status,
                "Kilder": price_detail,
                "Utestående": yield_detail + "; historisk validert retningsmodell mangler",
                "Handelssignal": "IKKE KLART",
            })

if TECH_NEWS in selected or MACRO_NEWS in selected:
    news_notes = []
    try:
        news_items += load_archived_news(at=now, within=timedelta(hours=4))
        news_notes.append("Telegram arkiv lest")
    except Exception as exc:
        news_notes.append(f"Telegram arkiv utilgjengelig ({type(exc).__name__})")
    try:
        news_items += load_archived_gdelt_news(
            at=now, database_path=DB_PATH, within=timedelta(hours=4),
        )
        news_notes.append("lokalt GDELT arkiv lest")
    except (FileNotFoundError, LookupError) as exc:
        news_notes.append(f"GDELT arkiv mangler ({type(exc).__name__})")
    except Exception as exc:
        news_notes.append(f"GDELT arkiv utilgjengelig ({type(exc).__name__})")
    counter = Counter(topic for item in news_items for topic in item.topics)
    for module in (TECH_NEWS, MACRO_NEWS):
        if module in selected:
            rows.append({
                "Modul": LABELS[module],
                "Data": f"{counter[module]} tematreff siste 4 t",
                "Kilder": "; ".join(news_notes),
                "Utestående": "Ingen validert påvirkningsretning eller avkastningsprognose fra nyheter",
                "Handelssignal": "IKKE KLART",
            })

st.subheader("Datatilgang per valgt modul")
st.dataframe(rows, hide_index=True, use_container_width=True)
st.caption(
    "Et 'VALID' prisvindu bekrefter kun tidsmessig komplett lagret 1m-historikk, "
    "ikke at Saxo-kursene er uten børstidsforsinkelse. 2/10/30Y kan bruke "
    "verifiserte, ferske futures-/CFD-proksyer som relative prosentbevegelser "
    "etter separat modellkalibrering, men aldri som basispunktendringer. "
    "Saxos tre testede Micro Yield-futures rapporterte 10 minutters forsinkelse "
    "20.11.2026 og er dermed ikke en godkjent rask impulsfeed. "
    "Nyheter må måles fra mottakstid, ikke kun publiseringstid."
)

if news_items:
    with st.expander("Klassifiserte, men ikke retningsbestemte nyhetskandidater"):
        st.dataframe([
            {
                "Mottatt UTC": item.received_at.isoformat(), "Kilde": item.source,
                "Moduler": ", ".join(item.topics), "Tekst": item.headline,
            }
            for item in news_items
            if any(module in selected for module in item.topics)
        ], hide_index=True, use_container_width=True)

result = synthesize(at=now, selected=selected, signals=(), horizon_minutes=horizon)
st.subheader("Felles syntese – forskningsstatus")
st.metric("Beslutning", result.direction)
st.info(
    "Ingen faktiske, ut-av-utvalg-validerte retningssignaler er koblet inn ennå. "
    "Derfor er syntesens status " + result.status + ", og den kan ikke sende "
    "posisjonsforslag til en AutoTrader-instans."
)
