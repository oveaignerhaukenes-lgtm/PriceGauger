from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from trading_desk_indicators import (
    INDICATOR_ATR, INDICATOR_BOLLINGER, INDICATOR_EMA20, INDICATOR_EMA50,
    INDICATOR_MACD, INDICATOR_RSI, INDICATOR_SMA50, INDICATOR_STOCHASTIC,
    INDICATOR_SWING_BANDS, INDICATOR_VWAP, TechnicalIndicators,
)


@dataclass(frozen=True, slots=True)
class IndicatorGuideV1:
    name: str
    short: str
    details: str
    regime_note: str


_GUIDES = {
    INDICATOR_BOLLINGER: IndicatorGuideV1(INDICATOR_BOLLINGER, "Pris relativt til glidende middel og volatilitetsbånd.", "Bollinger Bands består normalt av et glidende middel med øvre og nedre bånd flere standardavvik unna. Båndbredde sier noe om realisert volatilitet; berøring av et bånd er ikke i seg selv et reversalsignal.", "I sterke trender kan pris følge ytterbåndet lenge; i range er retur mot midtbåndet ofte mer informativt."),
    INDICATOR_MACD: IndicatorGuideV1(INDICATOR_MACD, "Momentum/trend fra avstanden mellom to eksponentielle snitt.", "MACD 12/26 sammenligner et raskt og tregt EMA; signallinjen er vanligvis et 9-perioders EMA av MACD. Kryss viser endring i relativt momentum, mens histogrammet viser avstanden mellom MACD og signal.", "Kryss med etablert trend har en annen betydning enn kryss mot trenden. Se også om avstanden utvider eller trekker seg sammen."),
    INDICATOR_RSI: IndicatorGuideV1(INDICATOR_RSI, "Relativ styrke i siste opp- og nedbevegelser, 0–100.", "RSI måler forholdet mellom gjennomsnittlige gevinster og tap. 70/30 er referanser for høy/lav momentumtilstand, ikke automatiske salgs- eller kjøpssignaler.", "I sterke trender kan RSI holde seg ekstrem lenge. Divergens og overgang gjennom regime-typiske nivåer er ofte mer nyttig."),
    INDICATOR_EMA20: IndicatorGuideV1(INDICATOR_EMA20, "Rask trendreferanse som vektlegger nyere priser.", "EMA 20 gir nyere priser større vekt enn eldre priser og brukes ofte som kort trend-/pullback-referanse.", "I trend kan reaksjoner rundt EMA være strukturstøtte; i chop gir kryss frem og tilbake lite alene."),
    INDICATOR_EMA50: IndicatorGuideV1(INDICATOR_EMA50, "Mellomrask trendreferanse med større treghet enn EMA 20.", "EMA 50 glatter pris over en lengre horisont og skiller kort støy fra et mer vedvarende trendnivå.", "Avstand, helning og retester er viktigere enn bare hvilken side av linjen prisen ligger på."),
    INDICATOR_SMA50: IndicatorGuideV1(INDICATOR_SMA50, "Likvektet gjennomsnitt av de siste 50 periodene.", "SMA 50 vekter alle 50 observasjoner likt og reagerer tregere på ferske prisendringer enn tilsvarende EMA.", "Best som struktur-/trendkontekst; i raske regimeskifter henger det naturlig etter."),
    INDICATOR_VWAP: IndicatorGuideV1(INDICATOR_VWAP, "Gjennomsnittspris vektet med registrert markedsvolum.", "Chart-VWAP er forankret i vist vindu og bruker canonical bars med positivt Saxo chart-volume. Quote sample_count brukes ikke som volum.", "Pris over/under VWAP beskriver handel relativt til volumvektet kostbasis; betydningen avhenger av trend, vindu og datadekning."),
    INDICATOR_STOCHASTIC: IndicatorGuideV1(INDICATOR_STOCHASTIC, "Hvor siste close ligger i nylig high–low-range.", "Stochastic %K skalerer dagens plassering i siste prisrange til 0–100; %D glatter %K.", "Mest nyttig i range/chop. I sterke trender kan den ligge ekstrem lenge."),
    INDICATOR_ATR: IndicatorGuideV1(INDICATOR_ATR, "Absolutt realisert volatilitet basert på true range.", "ATR inkluderer intrabar-range og gaps mot forrige close. Den sier hvor mye markedet beveger seg, ikke retning.", "Stigende ATR betyr ekspanderende bevegelse/risiko; fallende ATR betyr kompresjon."),
    INDICATOR_SWING_BANDS: IndicatorGuideV1(INDICATOR_SWING_BANDS, "Bekreftede lokale high/low-soner i prisstrukturen.", "Swing-sonene bygges fra bekreftede lokale pivoter og er en strukturreferanse, ikke en separat prediksjonsmodell.", "I trend brukes de som retest-/invalidation-kontekst; i range kan gjentatte reaksjoner være viktigere."),
}


def guide_for_indicator_v1(name: str) -> IndicatorGuideV1:
    return _GUIDES[str(name)]


def _last(points) -> float | None:
    return None if not points else float(points[-1].value)


def _previous(points) -> float | None:
    return None if len(points) < 2 else float(points[-2].value)


def quick_indicator_read_v1(name: str, technical: TechnicalIndicators | None, *, latest_close: float | None) -> str:
    if technical is None:
        return "Venter på nok canonical data."
    name = str(name)
    if name == INDICATOR_MACD:
        macd, signal = _last(technical.macd), _last(technical.macd_signal)
        hist, previous = _last(technical.macd_histogram), _previous(technical.macd_histogram)
        if macd is None or signal is None:
            return "Venter på MACD-warmup."
        side = "bullish" if macd > signal else "bearish" if macd < signal else "nøytralt"
        impulse = ""
        if hist is not None and previous is not None:
            impulse = " · avstanden øker" if abs(hist) > abs(previous) else " · avstanden kjølner"
        return f"{side}{impulse}"
    if name == INDICATOR_RSI:
        value = _last(technical.rsi)
        if value is None: return "Venter på RSI-warmup."
        state = "høyt momentum" if value >= 70 else "lavt momentum" if value <= 30 else "midt i rangen"
        return f"{value:.1f} · {state}"
    if name == INDICATOR_STOCHASTIC:
        k, d = _last(technical.stochastic_k), _last(technical.stochastic_d)
        if k is None: return "Venter på Stochastic-warmup."
        cross = "" if d is None else " · K over D" if k > d else " · K under D" if k < d else " · K≈D"
        return f"%K {k:.1f}{cross}"
    if name == INDICATOR_ATR:
        value = _last(technical.atr)
        return "Venter på ATR-warmup." if value is None else f"{value:.4g} · retning nøytral"
    if name == INDICATOR_BOLLINGER:
        middle, upper, lower = _last(technical.bollinger_middle), _last(technical.bollinger_upper), _last(technical.bollinger_lower)
        if latest_close is None or middle is None or upper is None or lower is None: return "Venter på Bollinger-warmup."
        place = "ved/over øvre bånd" if latest_close >= upper else "ved/under nedre bånd" if latest_close <= lower else "over midtbåndet" if latest_close >= middle else "under midtbåndet"
        return place
    line_points = {INDICATOR_EMA20: technical.ema20, INDICATOR_EMA50: technical.ema50, INDICATOR_SMA50: technical.sma50, INDICATOR_VWAP: technical.vwap}.get(name)
    if line_points is not None:
        value = _last(line_points)
        if latest_close is None or value is None: return "Venter på nok data."
        relation = "over" if latest_close > value else "under" if latest_close < value else "på"
        return f"Pris {relation} ({value:.4g})"
    if name == INDICATOR_SWING_BANDS:
        return "Bekreftede pivoter · struktursoner"
    return "Ingen kortlesning tilgjengelig."


def render_indicator_guide_v1(st, *, indicator_names: Iterable[str], technical: TechnicalIndicators | None, latest_close: float | None, trend_state: str, momentum_state: str, volatility_state: str, structure_state: str, ai_summary: str | None = None) -> None:
    selected = [str(item) for item in indicator_names if str(item) in _GUIDES]
    if not selected:
        return
    st.markdown("**Indikatorleser**")
    ai_key = "tradingdesk-indicator-ai-enabled"
    if ai_key not in st.session_state: st.session_state[ai_key] = False
    ai_enabled = st.toggle("AI-vurdering", key=ai_key, help="Av som standard. Når den er på, materialiserer workeren én kort persistert vurdering per valgt indikator og ny closed bar.")
    ai_snapshot = None
    if ai_enabled:
        try:
            from indicator_ai_insights_v1 import load_latest_indicator_ai_v1
            market = str(st.session_state.get("tradingdesk-v2-market", "") or "")
            timeframe = str(st.session_state.get("tradingdesk_timeframe", "5m") or "5m")
            ai_snapshot = load_latest_indicator_ai_v1(market=market, timeframe=timeframe, indicator_names=selected)
        except Exception:
            ai_snapshot = None
    if ai_summary: st.caption(f"Technical Interpreter · {ai_summary}")
    if ai_enabled and ai_snapshot is not None: st.caption(f"AI · bar {ai_snapshot.source_bar_time} · {ai_snapshot.model}")
    elif ai_enabled: st.caption("AI · venter på første vurdering")
    regime = f"Trend: {trend_state} · momentum: {momentum_state} · volatilitet: {volatility_state} · struktur: {structure_state}"
    for name in selected:
        guide = guide_for_indicator_v1(name)
        ai_note = None if ai_snapshot is None else ai_snapshot.assessments.get(name)
        with st.container(border=True):
            left, right = st.columns([5.5, 1], gap="small", vertical_alignment="center")
            with left:
                st.markdown(f"**{name}** · {quick_indicator_read_v1(name, technical, latest_close=latest_close)}")
                secondary = f"AI · {ai_note}" if ai_enabled and ai_note else guide.short
                st.caption(secondary)
            with right:
                with st.popover("Mer", use_container_width=True):
                    st.markdown(f"**Hva den måler**  \n{guide.short}")
                    st.write(guide.details)
                    st.markdown(f"**I regime**  \n{regime}")
                    st.write(guide.regime_note)
                    if ai_note:
                        st.markdown("**AI-vurdering nå**")
                        st.write(ai_note)
                    if ai_summary:
                        st.markdown("**Technical Interpreter**")
                        st.write(ai_summary)


__all__ = ["IndicatorGuideV1", "guide_for_indicator_v1", "quick_indicator_read_v1", "render_indicator_guide_v1"]
