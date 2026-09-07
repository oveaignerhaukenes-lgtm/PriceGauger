from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from trading_desk_indicators import (
    INDICATOR_ATR,
    INDICATOR_BOLLINGER,
    INDICATOR_EMA20,
    INDICATOR_EMA50,
    INDICATOR_MACD,
    INDICATOR_RSI,
    INDICATOR_SMA50,
    INDICATOR_STOCHASTIC,
    INDICATOR_SWING_BANDS,
    INDICATOR_VWAP,
    TechnicalIndicators,
)


@dataclass(frozen=True, slots=True)
class IndicatorGuideV1:
    name: str
    short: str
    details: str
    regime_note: str


_GUIDES = {
    INDICATOR_BOLLINGER: IndicatorGuideV1(
        INDICATOR_BOLLINGER,
        "Pris relativt til et glidende middel og et volatilitetsbånd.",
        "Bollinger Bands består normalt av et glidende middel med øvre og nedre bånd flere standardavvik unna. Båndbredde sier noe om realisert volatilitet; berøring av et bånd er ikke i seg selv et reversalsignal.",
        "I et sterkt trendregime kan pris følge ytterbåndet lenge. I et sidelengs regime er retur mot midtbåndet ofte mer informativt.",
    ),
    INDICATOR_MACD: IndicatorGuideV1(
        INDICATOR_MACD,
        "Momentum/trend målt som avstanden mellom to eksponentielle snitt.",
        "MACD 12/26 sammenligner et raskt og et tregt EMA; signallinjen er vanligvis et 9-perioders EMA av MACD. Kryss viser endring i relativt momentum, mens histogrammet viser avstanden mellom MACD og signal.",
        "Kryss i samme retning som et etablert trendregime har normalt en annen betydning enn kryss mot trenden. Se også på om avstanden faktisk utvider eller trekker seg sammen.",
    ),
    INDICATOR_RSI: IndicatorGuideV1(
        INDICATOR_RSI,
        "Relativ styrke i siste opp- og nedbevegelser, skalert 0–100.",
        "RSI måler forholdet mellom gjennomsnittlige gevinster og tap over en rullerende periode. 70/30 brukes ofte som referanser for høy/lav momentumtilstand, men nivåene er ikke automatiske salgs- eller kjøpssignaler.",
        "I sterke trender kan RSI holde seg høy eller lav lenge. Divergens og overgang tilbake gjennom regime-typiske nivåer er ofte mer nyttig enn et enkelt 70/30-treff.",
    ),
    INDICATOR_EMA20: IndicatorGuideV1(
        INDICATOR_EMA20,
        "Raskt glidende prisnivå som vektlegger nyere observasjoner.",
        "EMA 20 gir nyere priser større vekt enn eldre priser og brukes ofte som en kort trend-/pullback-referanse.",
        "I trendregimer kan gjentatte reaksjoner rundt EMA være strukturstøtte. I chop gir kryss frem og tilbake lite informasjon alene.",
    ),
    INDICATOR_EMA50: IndicatorGuideV1(
        INDICATOR_EMA50,
        "Mellomrask trendreferanse med større treghet enn EMA 20.",
        "EMA 50 glatter pris over en lengre horisont og brukes til å skille kort støy fra et mer vedvarende trendnivå.",
        "Avstand, helning og hvordan pris reagerer ved retester er viktigere enn bare hvilken side av linjen prisen befinner seg på.",
    ),
    INDICATOR_SMA50: IndicatorGuideV1(
        INDICATOR_SMA50,
        "Likvektet gjennomsnitt av de siste 50 periodene.",
        "SMA 50 er et enkelt glidende gjennomsnitt der alle 50 observasjoner teller like mye. Det reagerer tregere på ferske prisendringer enn et tilsvarende EMA.",
        "Det fungerer best som struktur-/trendkontekst. I raske regimeskifter vil det naturlig henge etter.",
    ),
    INDICATOR_VWAP: IndicatorGuideV1(
        INDICATOR_VWAP,
        "Gjennomsnittspris vektet med ekte registrert markedsvolum.",
        "PriceGauger sin chart-VWAP er forankret i det viste vinduet og bruker bare canonical bars med reelt positivt Saxo chart-volume. Quote sample_count brukes aldri som volum.",
        "Pris over/under VWAP kan beskrive hvor markedet handler relativt til volumvektet kostbasis, men effekten avhenger av trend, tidsvindu og datadekning.",
    ),
    INDICATOR_STOCHASTIC: IndicatorGuideV1(
        INDICATOR_STOCHASTIC,
        "Hvor siste close ligger i forhold til nylig high–low-range.",
        "Stochastic %K skalerer dagens plassering i den siste prisrangen til 0–100; %D glatter %K. Høye/lave nivåer betyr at close ligger nær toppen/bunnen av den valgte rangen.",
        "Oscillatoren er ofte mest nyttig i range/chop. I sterke trender kan den ligge ekstrem lenge uten at trenden er ferdig.",
    ),
    INDICATOR_ATR: IndicatorGuideV1(
        INDICATOR_ATR,
        "Absolutt realisert volatilitet basert på true range.",
        "ATR inkluderer både intrabar-range og gaps mot forrige close. Den sier hvor mye markedet beveger seg, ikke hvilken retning det skal gå.",
        "Stigende ATR betyr ekspanderende bevegelse/risiko; fallende ATR betyr kompresjon. Sammenlign helst ATR mot markedets egen nylige historikk.",
    ),
    INDICATOR_SWING_BANDS: IndicatorGuideV1(
        INDICATOR_SWING_BANDS,
        "Bekreftede lokale high/low-soner i den viste prisstrukturen.",
        "Swing-sonene bygges fra bekreftede lokale pivoter og er en visuell strukturreferanse, ikke en separat prediksjonsmodell.",
        "I trend brukes de ofte som retest-/invalidation-kontekst; i range kan gjentatte reaksjoner rundt samme område være viktigere.",
    ),
}


def guide_for_indicator_v1(name: str) -> IndicatorGuideV1:
    return _GUIDES[str(name)]


def _last(points) -> float | None:
    return None if not points else float(points[-1].value)


def _previous(points) -> float | None:
    return None if len(points) < 2 else float(points[-2].value)


def quick_indicator_read_v1(
    name: str,
    technical: TechnicalIndicators | None,
    *,
    latest_close: float | None,
) -> str:
    if technical is None:
        return "Venter på nok canonical data."
    name = str(name)
    if name == INDICATOR_MACD:
        macd = _last(technical.macd)
        signal = _last(technical.macd_signal)
        hist = _last(technical.macd_histogram)
        previous = _previous(technical.macd_histogram)
        if macd is None or signal is None:
            return "Venter på MACD-warmup."
        side = "bullish" if macd > signal else "bearish" if macd < signal else "nøytralt"
        impulse = ""
        if hist is not None and previous is not None:
            impulse = " · avstanden øker" if abs(hist) > abs(previous) else " · avstanden kjølner"
        return f"MACD er {side}{impulse}."
    if name == INDICATOR_RSI:
        value = _last(technical.rsi)
        if value is None:
            return "Venter på RSI-warmup."
        state = "høyt momentum" if value >= 70 else "lavt momentum" if value <= 30 else "midt i rangen"
        return f"RSI {value:.1f} · {state}."
    if name == INDICATOR_STOCHASTIC:
        k = _last(technical.stochastic_k)
        d = _last(technical.stochastic_d)
        if k is None:
            return "Venter på Stochastic-warmup."
        cross = ""
        if d is not None:
            cross = " · K over D" if k > d else " · K under D" if k < d else " · K≈D"
        return f"%K {k:.1f}{cross}."
    if name == INDICATOR_ATR:
        value = _last(technical.atr)
        return "Venter på ATR-warmup." if value is None else f"ATR {value:.4g} · retning nøytral."
    if name == INDICATOR_BOLLINGER:
        middle = _last(technical.bollinger_middle)
        upper = _last(technical.bollinger_upper)
        lower = _last(technical.bollinger_lower)
        if latest_close is None or middle is None or upper is None or lower is None:
            return "Venter på Bollinger-warmup."
        if latest_close >= upper:
            place = "ved/over øvre bånd"
        elif latest_close <= lower:
            place = "ved/under nedre bånd"
        elif latest_close >= middle:
            place = "over midtbåndet"
        else:
            place = "under midtbåndet"
        return f"Pris {place}."

    line_points = {
        INDICATOR_EMA20: technical.ema20,
        INDICATOR_EMA50: technical.ema50,
        INDICATOR_SMA50: technical.sma50,
        INDICATOR_VWAP: technical.vwap,
    }.get(name)
    if line_points is not None:
        value = _last(line_points)
        if latest_close is None or value is None:
            return "Venter på nok data."
        relation = "over" if latest_close > value else "under" if latest_close < value else "på"
        return f"Pris {relation} {name} ({value:.4g})."
    if name == INDICATOR_SWING_BANDS:
        return "Bekreftede pivoter vises som struktursoner."
    return "Ingen kortlesning tilgjengelig."


def render_indicator_guide_v1(
    st,
    *,
    indicator_names: Iterable[str],
    technical: TechnicalIndicators | None,
    latest_close: float | None,
    trend_state: str,
    momentum_state: str,
    volatility_state: str,
    structure_state: str,
    ai_summary: str | None = None,
) -> None:
    selected = [str(item) for item in indicator_names if str(item) in _GUIDES]
    if not selected:
        return
    st.markdown("**Indikatorleser**")
    ai_key = "tradingdesk-indicator-ai-enabled"
    if ai_key not in st.session_state:
        st.session_state[ai_key] = False
    ai_enabled = st.toggle(
        "AI-vurdering",
        key=ai_key,
        help="Av som standard. Når den er på, materialiserer workeren én kort persistert vurdering per valgt indikator og ny closed bar.",
    )

    ai_snapshot = None
    if ai_enabled:
        try:
            from indicator_ai_insights_v1 import load_latest_indicator_ai_v1

            market = str(st.session_state.get("tradingdesk-v2-market", "") or "")
            timeframe = str(st.session_state.get("tradingdesk_timeframe", "5m") or "5m")
            ai_snapshot = load_latest_indicator_ai_v1(
                market=market,
                timeframe=timeframe,
                indicator_names=selected,
            )
        except Exception:
            ai_snapshot = None

    if ai_summary:
        st.caption(f"Technical Interpreter · {ai_summary}")
    if ai_enabled and ai_snapshot is not None:
        st.caption(f"AI oppdatert fra bar {ai_snapshot.source_bar_time} · {ai_snapshot.model}")
    elif ai_enabled:
        st.caption("AI · venter på første worker-materialiserte vurdering.")

    regime = (
        f"Trend: {trend_state} · momentum: {momentum_state} · "
        f"volatilitet: {volatility_state} · struktur: {structure_state}"
    )
    for name in selected:
        guide = guide_for_indicator_v1(name)
        ai_note = None if ai_snapshot is None else ai_snapshot.assessments.get(name)
        with st.container(border=True):
            st.markdown(f"**{name}**")
            st.caption(quick_indicator_read_v1(name, technical, latest_close=latest_close))
            if ai_enabled:
                st.caption(f"AI · {ai_note}" if ai_note else "AI · venter på ny vurdering …")
            with st.popover("Fortell mer", use_container_width=True):
                st.markdown(f"**Hva den måler**  \n{guide.short}")
                st.write(guide.details)
                st.markdown(f"**I regime**  \n{regime}")
                st.write(guide.regime_note)
                if ai_note:
                    st.markdown("**AI-vurdering nå**")
                    st.write(ai_note)
                if ai_summary:
                    st.markdown("**Cached Technical Interpreter**")
                    st.write(ai_summary)


__all__ = [
    "IndicatorGuideV1",
    "guide_for_indicator_v1",
    "quick_indicator_read_v1",
    "render_indicator_guide_v1",
]
