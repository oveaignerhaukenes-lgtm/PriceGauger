"""Read-only V3 per-instance trading/indicator chart and AI decision ledger.

The chart is lazy: expensive market reads and one account-scoped, read-only
Saxo execution-price audit happen only after user opens the control. It cannot
place or cancel an order.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging

import pandas as pd
import streamlit as st

from autotrader_v3_ai_decision_memory_v1 import load_ai_decisions_v1
from autotrader_v3_ai_manager_shadow_v1 import shadow_settings_v1,save_shadow_settings_v1
from autotrader_v3_config_v1 import load_autotrader_config_v3
from autotrader_v3_instance_fill_prices_v1 import (
    attach_verified_fill_prices_v1, fetch_exact_final_fills_v1,
)
from canonical_market_bars_v2 import CanonicalMarketBarStoreV2
from database import connect
from trading_desk import ChartBar, utc
from trading_desk_indicators import calculate_indicators
from tradingdesk_ui.charts.lightweight.renderer import render_lightweight_live_chart_v1

LOGGER = logging.getLogger("pricegauger.v3.instance_inspection")
TF_MINUTES = {"1m": 1, "2m": 2, "5m": 5, "10m": 10,
              "15m": 15, "30m": 30, "1h": 60}


def resample_complete_candles_v1(
    bars, *, timeframe_minutes: int, now: datetime,
) -> tuple[ChartBar, ...]:
    """OHLC resampling from genuine closed canonical 1m bars, no synthetic fills.

    Reject the currently forming minute, incomplete aggregated bins and bins
    with missing intermediate 1m bars; future candles cannot affect a signal.
    """
    step=int(timeframe_minutes)
    if step not in TF_MINUTES.values():
        raise ValueError("unsupported indicator timeframe")
    now_utc=utc(now)
    minute_cutoff=now_utc.replace(second=0,microsecond=0)
    buckets={}
    for bar in bars:
        at=utc(bar.bar_time)
        if at >= minute_cutoff or at.second != 0 or at.microsecond != 0:
            continue
        key=at.replace(minute=at.minute-(at.minute % step),
                       second=0,microsecond=0)
        # Align 1h (and supported subhour resolutions) to UTC start.
        buckets.setdefault(key,[]).append((at,bar))
    result=[]
    for start,raw in sorted(buckets.items()):
        raw.sort(key=lambda x:x[0])
        expected=[start+timedelta(minutes=i) for i in range(step)]
        times=[t for t,_ in raw]
        if times != expected or start+timedelta(minutes=step)>minute_cutoff:
            continue
        items=[v for _,v in raw]
        result.append(ChartBar(
            market=str(items[0].market_name),bar_time=start.isoformat(),
            open=float(items[0].open), high=max(float(x.high) for x in items),
            low=min(float(x.low) for x in items), close=float(items[-1].close),
            volume=(sum(float(x.volume) for x in items if x.volume is not None)
                    if any(x.volume is not None for x in items) else None),
        ))
    return tuple(result)


def load_instance_executions_v1(
    *, instance_id: str, account_id: str, after: datetime, limit=250,
    db_path="pricegauger.db",
) -> tuple[dict, ...]:
    """Confirmed worker execution events, NOT request attempts or manual orders."""
    try:
        with connect(db_path) as db:
            rows=db.execute("""SELECT executed_at,action,side,amount,
                inventory_before,inventory_after,request_key,broker_order_id,
                instance_id,account_id
                FROM autotrader_v3_execution_events
                WHERE instance_id=? AND account_id=? AND executed_at>=?
                ORDER BY executed_at DESC,request_key DESC LIMIT ?""",
                (str(instance_id),str(account_id),utc(after),
                 max(1,min(1000,int(limit))))).fetchall()
        return tuple(dict(row) for row in reversed(rows))
    except Exception as exc:
        LOGGER.warning("V3 read-only execution projection unavailable type=%s",
                       type(exc).__name__)
        return ()


@st.cache_data(ttl=60,show_spinner=False)
def _verified_instance_fill_prices_cached_v1(
    account_id: str, uic: int, asset_type: str, event_specs: tuple,
) -> dict:
    """A single, cached, account-scoped Saxo audit read for an opened chart."""
    events=tuple(dict(broker_order_id=order_id,side=side,amount=amount,
                      executed_at=executed_at)
                 for order_id,side,amount,executed_at in event_specs)
    prices=fetch_exact_final_fills_v1(
        events,account_id=account_id,uic=int(uic),asset_type=asset_type)
    try:
        from live_mirror_audit_v1 import persist_verified_fills
        persist_verified_fills(prices,account_id=account_id,uic=int(uic),asset_type=asset_type)
    except Exception:
        LOGGER.warning("Mirror fill evidence could not be persisted")
    return prices


def _nearest_bar_anchor(bars: tuple[ChartBar,...], timestamp: datetime):
    """Find last already-observed candle for display only, never a fill quote."""
    stamp=utc(timestamp)
    matched=None
    for b in bars:
        if utc(b.bar_time) <= stamp:
            matched=b
        else:
            break
    return matched


def build_instance_inspection_payload_v1(
    bars: tuple[ChartBar, ...], executions=(), ai_decisions=(), *,
    timeframe_minutes: int, show_after: datetime | None = None,
    chart_id: str = "v3-inspection", instance_id: str | None = None,
    account_id: str | None = None,
) -> dict:
    """TV Lightweight Charts payload for three coordinated native panes.

    Indicator warmup uses all supplied completed candles; the visible candle,
    MACD, Stoch, execution and AI markers are clipped consistently.
    """
    if not bars:
        raise ValueError("no completed price candles")
    indicators=calculate_indicators(bars,macd_fast=12,macd_slow=26,macd_signal=9)
    cutoff=utc(show_after) if show_after else utc(bars[0].bar_time)
    kept=tuple(b for b in bars if utc(b.bar_time)>=cutoff)
    if not kept:
        raise ValueError("no candles in requested chart window")
    all_completed_by_time={utc(b.bar_time):b for b in bars}
    def unix(at):
        return int(utc(at).timestamp())
    def series(points):
        return [{"time":unix(p.bar_time),"value":float(p.value)}
                for p in points if utc(p.bar_time)>=cutoff]
    candle_data=[{"time":unix(b.bar_time),
                  "open":float(b.open),"high":float(b.high),
                  "low":float(b.low),"close":float(b.close)} for b in kept]
    markers=[]
    def chart_bar_at(when):
        bar=_nearest_bar_anchor(kept,when)
        if bar is None or utc(when)>utc(kept[-1].bar_time)+timedelta(minutes=timeframe_minutes):
            return None
        return bar
    for item in executions:
        if (instance_id is not None and str(item.get("instance_id") or "")!=str(instance_id)
            or account_id is not None and str(item.get("account_id") or "")!=str(account_id)):
            continue
        exact_price=item.get("execution_price") if item.get("price_source")=="SAXO_FINAL_FILL" else None
        verified=exact_price is not None and float(exact_price)>0
        when=utc(item.get("filled_at") if verified else item["executed_at"])
        bar=chart_bar_at(when)
        if bar is None:
            continue
        side=str(item.get("side") or "").upper()
        inventory_after=item.get("inventory_after")
        is_flat=(inventory_after is not None and abs(float(inventory_after))<1e-12
                 and str(item.get("action") or "").upper()=="CLOSE")
        up=side=="BUY"
        if side not in {"BUY","SELL"}:
            continue
        # With no exact broker FinalFill, use only a *previously completed*
        # candle close as an explicitly unverified reference. Never the high
        # on a SELL or the low on a BUY (retrospective best-case execution).
        # Exact prior finished timeframe bucket; never bridge a price gap,
        # and include the warmup bar preceding the visible chart window.
        prior=when-timedelta(minutes=timeframe_minutes)
        prior_bucket=prior.replace(
            minute=prior.minute-(prior.minute % timeframe_minutes),
            second=0,microsecond=0)
        reference=all_completed_by_time.get(prior_bucket)
        if not verified and reference is None:
            continue
        markers.append({"time":unix(bar.bar_time),
                        "price":float(exact_price if verified else reference.close),
                        "position":"belowBar" if up else "aboveBar",
                        # Native fallback only; shared renderer draws SVG markers.
                        "shape":"square" if is_flat else ("arrowUp" if up else "arrowDown"),
                        "color":"#94a3b8" if is_flat else ("#38bdf8" if up else "#c084fc"),
                        "text":"","side":side,"action":str(item.get("action") or ""),
                        "size":0.45,"source":"AUTOTRADER_V3",
                        "position_direction":"FLAT" if is_flat else ("LONG" if up else "SHORT"),
                        "inventory_after":inventory_after,
                        "price_source":"SAXO_FINAL_FILL" if verified else "PREVIOUS_CLOSED_BAR_REFERENCE",
                        "price_verified":verified,
                        "account_id":str(item.get("account_id") or ""),
                        "instance_id":str(item.get("instance_id") or "")})
    for item in ai_decisions:
        bar=chart_bar_at(utc(item["evaluated_at"]))
        if bar is None:
            continue
        action=str(item.get("action") or "?")
        markers.append({"time":unix(bar.bar_time),"position":"aboveBar",
                        "shape":"circle","color":"#9A6ADD",
                        "text":f"AI {action}"[:28],"source":"AI_SHADOW"})
    markers.sort(key=lambda x:x["time"])
    return {
        "chart_id":chart_id,
        "signature":f"v3-inspection:{timeframe_minutes}:3-panes",
        "market":kept[-1].market,"timeframe":f"{timeframe_minutes}m",
        "height":420,"vertical_touch_drag":True,"pane_order":["price","macd","stochastic"],
        "price_panel_share":.43,
        "candles":candle_data,
        "lines":[
            {"role":"macd","label":"MACD 12/26","pane":"macd","data":series(indicators.macd)},
            {"role":"macd_signal","label":"Signal 9","pane":"macd","data":series(indicators.macd_signal)},
            {"role":"stochastic_k","label":"Stochastic %K 14","pane":"stochastic","data":series(indicators.stochastic_k)},
            {"role":"stochastic_d","label":"Stochastic %D 3","pane":"stochastic","data":series(indicators.stochastic_d)},
        ],
        "histograms":[{"role":"macd_hist","label":"MACD histogram",
                       "pane":"macd","data":series(indicators.macd_histogram)}],
        "thresholds":{"stochastic":[20,80]},
        "markers":markers,
    }


def render_v3_instance_inspection_v1(instance, *, key_prefix="fleet") -> None:
    """Embedded below each V3 instance in Fleet and TradingDesk; default idle."""
    instance_id=str(instance.instance_id)
    key=f"{key_prefix}:inspect:{instance_id}"
    if not st.toggle("Vis handelskart, MACD, Stochastic og AI-minne",
                     value=False,key=key):
        return
    config=load_autotrader_config_v3(instance_id)
    live_ai_enabled=('ai-loss-manager' in config.modifiers)
    manager_title=("AI Manager · LIVE (kan redusere/lukke posisjoner)"
                   if live_ai_enabled else
                   "AI Manager · SHADOW (analyserer tap, ingen ordre)")
    with st.expander(manager_title,expanded=False):
        settings=shadow_settings_v1(instance_id)
        enabled=st.toggle("AI tapsvurdering på denne instansen",
                          value=settings["enabled"],
                          key=f"{key_prefix}:ai-shadow-enabled:{instance_id}")
        seconds=st.slider("Tidsgrense for vedvarende tap (sekunder)",
                          min_value=15,max_value=180,step=5,
                          value=settings["trigger_seconds"],
                          key=f"{key_prefix}:ai-shadow-delay:{instance_id}")
        if live_ai_enabled:
            st.caption("AI Manager er valgt i LIVE-konfigurasjonen. "
                       "Den samme modellen vurderer tap og kan redusere eller lukke "
                       "en posisjon gjennom vanlig Saxo LIVE-kjede; AI åpner ikke "
                       "eller reverserer til ny posisjon. LIVE ON/OFF på instansen "
                       "styrer faktisk handel. Ingen ekstra godkjenningsknapp.")
        else:
            st.caption("AI-manageren vurderer kun i SHADOW. "
                       "Velg AI Loss Manager · LIVE under Options/modifiers "
                       "i instansens kontrollpanel for aktiv posisjonsforvaltning.")
        st.caption("Standard 60 sekunder · vurdering hvert 30. sekund · "
                   "3 minutter mellom AI-kall. Manglende AI-nøkkel eller "
                   "markedsdata fører ikke til AI-inngrep.")
        if (enabled!=settings["enabled"] or seconds!=settings["trigger_seconds"]):
            if st.button("Lagre AI SHADOW-innstillinger",
                         key=f"{key_prefix}:ai-shadow-save:{instance_id}"):
                save_shadow_settings_v1(
                    instance_id=instance_id,enabled=enabled,
                    trigger_seconds=seconds)
                st.success("AI SHADOW-innstillinger oppdatert.")
                st.rerun()
    timeframe=str(config.timeframe)
    if timeframe not in TF_MINUTES:
        st.info("Grafen krever en fast signalperiode i aktiv konfigurasjon.")
        return
    tf_minutes=TF_MINUTES[timeframe]
    window=st.selectbox("Vis siste",("6 timer","12 timer","24 timer","48 timer"),
                        index=2,key=f"{key_prefix}:inspect-window:{instance_id}")
    hours={"6 timer":6,"12 timer":12,"24 timer":24,"48 timer":48}[window]
    now=datetime.now(timezone.utc)
    # Warm up MACD for 34 completed signal candles; loading is capped/lazy.
    fetch_hours=min(160,max(hours+8, hours+tf_minutes*44/60))
    try:
        source=CanonicalMarketBarStoreV2().load_instrument_range(
            instrument_id=int(instance.instrument_id),
            start=now-timedelta(hours=fetch_hours),end=now,limit=10000)
        bars=resample_complete_candles_v1(
            source,timeframe_minutes=tf_minutes,now=now)
        visible=tuple(b for b in bars if utc(b.bar_time)>=now-timedelta(hours=hours))
        executions=load_instance_executions_v1(
            instance_id=instance_id,account_id=str(instance.account_id),
            after=now-timedelta(hours=hours))
        verified_prices={}
        if executions:
            try:
                specs=tuple((str(x.get("broker_order_id") or ""),
                             str(x["side"]),float(x["amount"]),
                             utc(x["executed_at"]).isoformat()) for x in executions)
                verified_prices=_verified_instance_fill_prices_cached_v1(
                    str(instance.account_id),int(instance.uic),
                    str(instance.asset_type),specs)
            except Exception as exc:
                LOGGER.warning("V3 inspector broker fill audit unavailable type=%s",
                               type(exc).__name__)
        executions=attach_verified_fill_prices_v1(executions,verified_prices)
        ai_decisions=load_ai_decisions_v1(
            instance_id=instance_id,account_id=str(instance.account_id),
            instrument_id=int(instance.instrument_id),limit=50)
        if not visible:
            st.info("Ingen komplette kanoniske candles for valgt konto/instrument og periode.")
            return
        if len(bars)<35:
            st.warning("For få ferdige signalbarer til full MACD 12/26/9.")
        # Native TradingView Lightweight Charts; reuse canonical 3-pane renderer.
        payload=build_instance_inspection_payload_v1(
            bars,executions=executions,ai_decisions=ai_decisions,
            timeframe_minutes=tf_minutes,
            show_after=now-timedelta(hours=hours),
            chart_id=f"v3-inspection:{instance_id}:{key_prefix}",
            instance_id=instance_id,account_id=str(instance.account_id))
        render_lightweight_live_chart_v1(
            payload,key=f"{key_prefix}:inspect-chart:{instance_id}")
    except Exception as exc:
        LOGGER.warning("V3 inspection panel load failed instance=%s type=%s",
                       instance_id,type(exc).__name__)
        st.info("Inspeksjonsgrafen kunne ikke lastes: "+type(exc).__name__)
        return
    st.caption(
        f"Aktiv strategi: {config.strategy_key} · {timeframe}. "
        "Pris/MACD/Stoch bruker fullstendige kanoniske 1m-barer og felles TA-kode. "
        f"Viser bare handler fra konto {str(instance.account_id)} og denne instansen. "
        f"Saxo-verifisert pris: {sum(bool(x.get('execution_price')) for x in executions)} "
        f"av {len(executions)} handler. "
        "Hule markører er ANSLAG fra forrige ferdige bar, ikke utførelsespris. "
        "Historikken kan omfatte tidligere strategier på samme instans. "
        "Dra langs prisaksen for vertikal zoom; scroll siden utenfor grafen."
    )
    if executions:
        with st.expander(f"Ordrehistorikk · {len(executions)} registrerte utførelser"):
            st.dataframe(pd.DataFrame([{
                "Avstemming UTC":utc(x["executed_at"]),
                "Saxo fill UTC":(utc(x["filled_at"]) if x.get("filled_at") else None),
                "Handling":x["action"],"Side":x["side"],
                "Antall":x["amount"],"Posisjon etter":x["inventory_after"],
                "Saxo-fillpris":x.get("execution_price"),
                "Prisstatus":"Saxo FinalFill" if x.get("execution_price") else "Kun referanse",
                "Request":str(x["request_key"])[:14]
            } for x in reversed(executions)]),
            use_container_width=True,hide_index=True)
    st.markdown("**AI-beslutninger · varig etterprøvbart minne**")
    if not ai_decisions:
        st.caption("Ingen AI-vurderinger lagret for denne instansen ennå. "
                   "AI Manager i SHADOW kan skrive faktiske begrunnelser her; "
                   "ingen retrospektive forklaringer blir oppdiktet.")
    else:
        labels=[f"{utc(x['evaluated_at']):%d.%m %H:%M:%S} UTC · "
                f"{x['mode']} {x['action']} · {x['model_id']}"
                for x in ai_decisions]
        for i,entry in enumerate(ai_decisions):
            with st.expander(labels[i],expanded=False):
                st.write(str(entry["reason"]))
                st.caption(
                    f"Strategi: {entry['strategy_key']} · "
                    f"confidence {float(entry['confidence']):.2f} · "
                    f"grunnlag {entry['evidence_as_of']} · "
                    f"snapshot SHA256 {entry['evidence_hash']}"
                )
                import json
                st.json(json.loads(entry["evidence_json"]))


__all__=["resample_complete_candles_v1",
         "load_instance_executions_v1",
         "build_instance_inspection_payload_v1",
         "render_v3_instance_inspection_v1"]
