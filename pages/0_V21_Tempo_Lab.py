"""V2.1 subminute study: native recorded Saxo quotes, PAPER only."""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import json

import pandas as pd
import streamlit as st

from database import connect
from instrument_registry_v2 import list_subscribed_sources_v2
from macd_stoch_v21_30s_research_v1 import (
    MAX_QUOTES, run_v21_quote_paper_v1, validate_quotes_v1,
)

st.set_page_config(page_title="V2.1 Tempo-lab · PriceGauger", layout="wide")
st.title("V2.1 Tempo-lab · 15s / 30s / 1m")
st.caption("V2.1 FLAT-først, V2.1 direkte PAPER NET-flip og V2.2 Flip, på 15s/30s/1m.")
st.warning(
    "PAPER-forskning, ikke LIVE. Direkte flip innebærer aldri tillatelse til "
    "å fjerne posisjons-, ordre-, risikogrense- eller Saxo-kontroller. "
    "Ingen ordrefunksjoner eller kontoinnstillinger brukes her."
)
st.info(
    "Bruker faktisk tidsstemplet bid/ask-historikk fra separat "
    "lsim_hyper_quotes_1s, ikke interpolerte halvminuttersbarer fra 1m. "
    "Modellen har de samme indikatorperiodene i antall barer: 15s-versjonen "
    "har dermed vesentlig kortere effektiv indikatorhorisont enn 1m-versjonen. "
    "Sammenligningen er forskning, ikke bevis på et overlegent LIVE-resultat."
)

try:
    sources = list_subscribed_sources_v2(provider="saxo")
except Exception as exc:
    sources = ()
    st.error("Kunne ikke hente Saxo-instrumentoversikt: " + type(exc).__name__)
if not sources:
    st.stop()
options = [
    x for x in sources if ("TECH" in x.market_name.upper()
                           or "NAS" in x.market_name.upper())
    and str(x.provider_instrument_id).isdigit()
]
if not options:
    st.warning("Ingen abonnerte Saxo Tech100-produkter finnes i kanonisk register.")
    st.stop()
source = st.selectbox(
    "Marked/UIC – eksakt Saxo kilde", options,
    format_func=lambda x: (
        f"{x.market_name} · {x.display_name} · UIC {x.provider_instrument_id}"
    ), key="tempo:instrument",
)
a, b, c = st.columns(3)
hours = a.selectbox("Registrert historikk", (3, 6, 12, 24), index=1,
                    format_func=lambda x: f"Siste {x} timer", key="tempo:hours")
delay = b.selectbox(
    "Antatt ekstra ordre- / beslutningslatens", (0, 1, 3, 5), index=1,
    format_func=lambda x: f"{x} s", key="tempo:delay",
)
max_lots = c.selectbox(
    "PAPER-maksposisjon", (.01, .02, .03), index=2,
    format_func=lambda x: f"{x:.2f} lot", key="tempo:lots",
)

if st.button("Kjør ni sammenlignbare PAPER-varianter", type="primary", key="tempo:run"):
    try:
        end = datetime.now(timezone.utc)
        start = end - timedelta(hours=int(hours))
        with connect() as db:
            raw = db.execute(
                """SELECT quote_at,received_at,bid,ask
                   FROM lsim_hyper_quotes_1s
                   WHERE provider_uic=? AND quote_at>=? AND quote_at<=?
                   ORDER BY quote_at LIMIT ?""",
                (int(source.provider_instrument_id),start.isoformat(),
                 end.isoformat(),MAX_QUOTES+1),
            ).fetchall()
        if len(raw) > MAX_QUOTES:
            raise ValueError("For mange kurser i valgt intervall. Velg færre timer.")
        if len(raw) < 500:
            raise ValueError(
                "For få lagrede 1s bid/ask-kurser for dette instrumentet. "
                "Samleren må ha vært aktiv – manglende historikk kan ikke rekonstrueres."
            )
        quotes = validate_quotes_v1([dict(x) for x in raw])
        results = []
        for seconds in (15, 30, 60):
            for model, mode in (
                ("v21","flat_first"),("v21","direct_1bar"),
                ("v22","flat_first"),
            ):
                results.append(run_v21_quote_paper_v1(
                    quotes, seconds=seconds, market=source.market_name,
                    observed_through=end, max_inventory=float(max_lots),
                    reversal_mode=mode, decision_model=model,
                    hypothetical_latency_seconds=int(delay),
                ))
        st.session_state["tempo:result"] = {
            "key": (int(source.provider_instrument_id), hours, delay, max_lots),
            "quotes": len(quotes), "start": start.isoformat(), "end": end.isoformat(),
            "results": results,
            "market": source.market_name,
            "uic": str(source.provider_instrument_id),
        }
    except (ValueError, TypeError, OverflowError) as exc:
        st.session_state.pop("tempo:result", None)
        st.error("Ingen gyldig test: " + str(exc)[:350])
    except Exception as exc:
        st.session_state.pop("tempo:result", None)
        st.error(
            "Kunne ikke lese eller evaluere quote-historikken: "
            + type(exc).__name__
        )
result = st.session_state.get("tempo:result")
if result and result["key"] != (
    int(source.provider_instrument_id), hours, delay, max_lots
):
    st.info("Innstillingene er endret. Kjør analysen på nytt.")
elif result:
    st.subheader("Sekunddata – sammenligning")
    st.caption(
        f"{result['market']} / UIC {result['uic']} · "
        f"{result['quotes']} reelle tidfestede bid/ask-observasjoner "
        f"mellom {result['start']} og {result['end']} (UTC)."
    )
    scores = []
    for x in result["results"]:
        scores.append({
            "Bar": f"{x.interval_seconds}s",
            "Modell": "V2.2 Flip" if x.decision_model=="v22" else "V2.1",
            "Reverseringsmåte": (
                "V2.2 motsatt strategimål"
                if x.decision_model=="v22" else
                "FLAT først (dagens V2.1)" if x.reversal_mode == "flat_first"
                else "NET-flip 1 bar (PAPER)"
            ),
            "Gyldige barer": x.bars,
            "Evaluerte barer": x.modeled_bars,
            "Handelsendringer": len(x.actions),
            "Åpne segmenter ved databrudd/slutt": x.incomplete_segments,
            "Manglende fersk quote ved beslutning": x.skipped_no_fill,
            "Ferdigavsluttet resultat (punkt × lot)": (
                round(x.hypothetical_pnl_points_lots, 5)
                if x.hypothetical_pnl_points_lots is not None else None
            ),
            "Uavsluttet markert P/L (punkt × lot)": (
                round(x.marked_unrealized_points_lots, 5)
                if x.incomplete_segments else None
            ),
            "Teoretisk største drawdown (punkt × lot)": (
                round(x.max_drawdown_points_lots, 5)
                if x.max_drawdown_points_lots is not None else None
            ),
        })
    st.dataframe(pd.DataFrame(scores), hide_index=True, use_container_width=True)
    st.warning(
        "P/L i punkt × lot er IKKE kroner, ingen Saxo-kontraktsmultiplikator, "
        "FX-konvertering, CFD-finansiering, kommisjon, slippage, margin eller faktisk fill. "
        "Quoted bid/ask er medregnet. Segmenter med åpne posisjoner rapporteres "
        "med separat markering; samlet resultat holdes tilbake når "
        "markedshistorikken ikke viser en faktisk testavslutning. "
        "Felles 60 minutters oppvarmingstid per sammenhengende datasegment er brukt. Kortere intervaller har fortsatt kortere teknisk indikatorhorisont."
    )
    ready = all(x.modeled_bars >= 50 for x in result["results"])
    closed = all(x.incomplete_segments == 0 for x in result["results"])
    if ready and closed:
        pairs = []
        for seconds in (15, 30, 60):
            base = next(x for x in result["results"] if x.interval_seconds == seconds and x.decision_model=="v21"
                        and x.reversal_mode == "flat_first")
            flip = next(x for x in result["results"] if x.interval_seconds == seconds and x.decision_model=="v21"
                        and x.reversal_mode == "direct_1bar")
            pairs.append((
                seconds, flip.hypothetical_pnl_points_lots
                - base.hypothetical_pnl_points_lots
            ))
        best_delay = max(pairs, key=lambda item: item[1])
        if best_delay[1] > 0:
            st.info(
                f"Med valgt latens hadde NET-flip positiv forskjell mot "
                f"FLAT-først ved {best_delay[0]}s "
                f"({best_delay[1]:+.4f} punkt × lot). Dette er kun en "
                "historisk PAPER-observasjon; IKKE en anbefaling om LIVE-flip."
            )
        else:
            st.info(
                "I denne prøven forbedret ikke direkte NET-flip samlet "
                "hypotetisk resultat mot dagens FLAT-først-regel."
            )
    else:
        st.info(
            "Datagrunnlaget er ennå ikke tilstrekkelig for en forsvarlig vinner. "
            "Vent på lengre reell sammenhengende dekning og fullførte testsegmenter."
        )
    with st.expander("Vis de 100 siste hypotetiske handelsendringene"):
        details = []
        for res in result["results"]:
            for x in res.actions[-100:]:
                details.append({
                    "Tidsramme": f"{res.interval_seconds}s",
                    "Variant":res.decision_model+" / "+res.reversal_mode,
                    **asdict(x),
                })
        st.dataframe(pd.DataFrame(details), hide_index=True, use_container_width=True)
    st.download_button(
        "Eksporter PAPER-rapport (JSON)",
        json.dumps({
            "schema": "PG_V21_15S_30S_1M_PAPER_V1",
            "instrument": {"market": result["market"], "uic": result["uic"]},
            "range_utc": [result["start"], result["end"]],
            "source_observations": result["quotes"],
            "extra_hypothetical_latency_seconds": delay,
            "notes": [
                "Genuine archived Saxo BBO, not synthetic subminute candles",
                "All execution attempts are simulations on next quote, not broker fills",
                "P/L in index points times Saxo lots, not NOK or total account P/L",
                "V2.2 models target reversal; actual LIVE Saxo still CLOSE -> confirmed FLAT -> OPEN, so this PAPER proxy is optimistic about live latency",
                "NET-flip tests one confirmed closed bar only; no LIVE authority",
                "Open end/gap exposure is marked separately and suppresses finished total",
                "No allowance for financing, slippage, commission, funding, cash/FX",
            ],
            "results": [{**{k: v for k,v in asdict(x).items() if k != "actions"},
                         "actions": [asdict(z) for z in x.actions]}
                        for x in result["results"]],
        }, ensure_ascii=False, allow_nan=False),
        file_name="v21_15s_30s_1m_paper.json",
        mime="application/json", key="tempo:export",
    )
else:
    st.caption("Velg UIC og tidsperiode, og kjør en isolert PAPER-sammenligning.")
