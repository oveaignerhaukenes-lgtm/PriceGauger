"""Pure chronological PAPER regime-selector research (not LIVE)."""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime,timedelta,timezone
import json

import pandas as pd
import streamlit as st

from autotrader_v3_trade_gate_research_v1 import (
    build_causal_gate_windows,evaluate_trade_gate_train_holdout,
)
from canonical_market_bars_v2 import CanonicalMarketBarStoreV2
from instrument_registry_v2 import list_subscribed_sources_v2
from strategy_lab_v2_replay import (
    ReplayCostsV2,replay_v3_strategy_v2,MAX_BARS,
)

st.set_page_config(page_title="AutoTrader · Trade eller FLAT",layout="wide")
st.title("AutoTrader · Trade eller stå FLAT?")
st.caption(
    "Første PAPER-baserte mønstermodell: ferdige 30m prisformer som "
    "inngangssignal for en prognose om neste 30m strategiresultat. "
    "70 % av tilgjengelige vinduer brukes kun til læring; siste 30 % "
    "blir utprøvd kronologisk, med tidsmessig purge."
)
st.warning(
    "Dette er IKKE en aktiv LIVE-guard. Det er ikke en AI-nevralsystem-"
    "modell eller en full simulering av at man går FLAT! "
    "Når strategien stopper eller starter på nytt, endres ordre og "
    "spreadkostnader. Først må dette testes med full kontospesifikk "
    "PAPER-ordreutførelse, konto-NAV og senere uavhengige uker."
)
try:
    sources=tuple(x for x in list_subscribed_sources_v2(provider="saxo")
                  if str(x.provider_instrument_id).isdigit()
                  and any(key in x.market_name.lower()
                          for key in ("tech","nas")))
except Exception as exc:
    st.error("Saxo abonnement utilgjengelig: "+type(exc).__name__)
    st.stop()
if not sources:
    st.warning("Ingen abonnerte Tech100 1m-kilder.")
    st.stop()
source=st.selectbox(
    "Eksakt marked/UIC",sources,
    format_func=lambda x:f"{x.market_name} · {x.display_name} · UIC {x.provider_instrument_id}",
)
strategy=st.selectbox("PAPER-baseline",(
    "macd-stoch-v2-1","macd-stoch-v2-2-flip",
    "macd-stoch-rhythm-build","macd-histogram","macd-flip",
    "pricetrend-1","sma-9-21-baseline"))
timeframe=st.selectbox("Signalperiode",("1m","2m"),index=0)
if strategy in ("macd-stoch-rhythm-build",):
    timeframe="1m"
if strategy in ("pricetrend-1","sma-9-21-baseline"):
    timeframe="2m"
hours=st.selectbox("Historikk i timer",(12,24,36,48),index=3)
a,b,c=st.columns(3)
spread=a.number_input("Spread i bp (scenario)",min_value=0.,value=2.0,step=.5)
point=c.number_input("NOK per punkt/lot (scenario)",min_value=.01,
                     value=10.,step=1.)
fees=b.number_input("Øvrige variable gebyrer i bp per side",
                    min_value=0.,value=0.,step=.5)
d,e,f=st.columns(3)
fixed=d.number_input("Fast gebyr per ordre NOK",min_value=0.,
                     value=1.,step=.5)
lots=e.number_input("Maks posisjon lot",min_value=.01,
                    value=.03,step=.01,format="%.2f")
capital=f.number_input("PAPER start NAV NOK",min_value=100.,
                       value=10000.,step=1000.)

if st.button("Evaluer markedsformer på tidsadskilt data",type="primary"):
    try:
        now=datetime.now(timezone.utc)
        start=now-timedelta(hours=hours)
        # Load warmup for 2m MACD, plus selected 12-48h.
        end=now
        bars=CanonicalMarketBarStoreV2().load_instrument_range(
            instrument_id=int(source.instrument_id),
            start=start-timedelta(hours=8),end=end,limit=MAX_BARS+1)
        if len(bars)>MAX_BARS:
            raise ValueError("3000 1m-grense overskredet: velg færre timer.")
        if len(bars)<240:raise ValueError("For få ekte historiske 1m-barer")
        costs=ReplayCostsV2(
            point_value_nok=float(point),
            spread_bps=float(spread),variable_fee_bps=float(fees),
            fixed_fee_nok=float(fixed),
            lot_step=.01,max_lots=float(lots),starting_nav_nok=float(capital),
            source="MANUAL_COST_SCENARIO_NOT_SAXO_BOOKED",
        )
        replay=replay_v3_strategy_v2(
            strategy_key=strategy,bars=bars,costs=costs,timeframe=timeframe)
        windows=build_causal_gate_windows(
            bars=bars,points=replay.points,spread_bps=float(spread),
            start=start,end=end)
        result=evaluate_trade_gate_train_holdout(windows)
        st.session_state["tradegate:report"]={
            "key":(int(source.instrument_id),strategy,timeframe,hours,
                   spread,fees,point,fixed,lots,capital),
            "asof":now.isoformat(),"data":windows,"evaluation":result,
            "source":source.market_name,"uic":source.provider_instrument_id,
            "replay_trades":replay.trades,
            "replay_costs":replay.total_cost_nok,
            "replay_dd":replay.drawdown_pct,"replay_gap_segments":replay.skipped_gaps,
        }
    except Exception as exc:
        st.session_state.pop("tradegate:report",None)
        st.error("PAPER-analysen feilet: "+type(exc).__name__+": "+str(exc)[:220])

report=st.session_state.get("tradegate:report")
if report:
    key=(int(source.instrument_id),strategy,timeframe,hours,
         spread,fees,point,fixed,lots,capital)
    if report["key"]!=key:
        st.warning("Innstillingene er endret. Kjør på nytt.")
    else:
        rows=report["data"]
        st.metric("Fullstendige fremoverskuende 30m-observasjoner",len(rows))
        st.caption(f"Baseline: {report['replay_trades']} PAPER-handler "
                   f"og {report['replay_costs']:.2f} scenario-NOK kostnader i "
                   "hele det tilgjengelige replay-vinduet, ikke bare gate-vinduet.")
        if rows:
            st.dataframe(pd.DataFrame([{
                "Ferdig form kl":r.decision_at,
                "Form":r.class_key,
                "Effektivitet":round(r.price_efficiency,3),
                "Svingpunkter":r.completed_turns,
                "Svingamplitude bp":r.median_swing_bps,
                "Range bp":round(r.range_bps,2),
                "Spread bp scenario":r.spread_bps,
                "Neste 30m PAPER NAV %":round(r.future_paper_nav_pct,3),
            }for r in rows]),hide_index=True,use_container_width=True)
        r=report["evaluation"]
        st.subheader("Tidsskilt vurdering av TRADE / SKIP")
        if r is None:
            st.warning("For lite sammenhengende pris- og PAPER-historikk: "
                       "trenger minst 14 treningsvinduer, 5 testvinduer "
                       "og en tidsmessig purge. Ingen gate kan rangeres ennå.")
        else:
            st.caption(f"Treningsgrense {r.train_cutoff.isoformat()} UTC · "
                       f"{r.train_windows} treningsvinduer · {r.test_windows} "
                       f"holdoutvinduer · {r.purged_windows} purgede · "
                       f"{r.abstained_windows} uten lært kategori.")
            st.dataframe(pd.DataFrame([{
                "Markedsform":name,"Beslutning i PAPER":action,
                "Treningsvinduer":count,"Neste 30m gj.sn. PAPER NAV %":round(avg,3),
            }for name,action,count,avg in r.trained_actions]),
            hide_index=True,use_container_width=True)
            a,b,c=st.columns(3)
            a.metric("Alle holdout-vinduer: sum PAPER %",f"{r.holdout_baseline_sum_pct:+.2f}")
            b.metric("Bare TRADE-vinduer: sum PAPER %",f"{r.holdout_only_allowed_sum_pct:+.2f}")
            c.metric("SKIP-vinduer som tapte: sum PAPER %",
                     f"{r.holdout_skipped_negative_sum_pct:+.2f}")
            st.caption(
                "Tallene er **summerte**, ikke kompounderte 30m-avkastninger. "
                "SKIP-vinduer som egentlig ga gevinst mister også "
                f"{r.holdout_skipped_positive_sum_pct:+.2f} prosentpoeng i "
                "denne PROXY-modellen. Ingen av tallene er avkastning fra "
                "en implementert FLAT-strategi. Krever fullstendig PAPER "
                "med faktiske exit/re-entry-kostnader før videre beslutninger."
            )
        export={
            "schema":"V3_CAUSAL_TRADE_GATE_RESEARCH_V1",
            "source":report["source"],"uic":report["uic"],
            "strategy":strategy,"timeframe":timeframe,
            "asof_utc":report["asof"],"windows":[asdict(v) for v in rows],
            "holdout_evaluation":asdict(r) if r else None,
            "notes":"Read-only research, incomplete FLAT-state model, no account impact.",
        }
        st.download_button(
            "Eksporter form/utfall/holdout (JSON)",
            json.dumps(export,ensure_ascii=False,default=str,allow_nan=False),
            file_name="pricegauger_trade_gate_paper.json",
            mime="application/json",
        )
