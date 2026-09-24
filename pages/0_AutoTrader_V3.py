from __future__ import annotations

import streamlit as st

from autotrader_strategy_enrollment_v2 import load_active_strategy_enrollments_v2
from autotrader_v3_config_v1 import AutoTraderConfigV3, load_autotrader_config_v3, save_autotrader_config_v3
from autotrader_v3_live_authority_v1 import live_authority_armed_v3
from autotrader_v3_modifier_settings_v1 import load_modifier_settings_v3, save_modifier_settings_v3
from autotrader_v3_registry_v1 import CONTROL_MODES_V3, MODIFIERS_V3, STRATEGIES_V3, TIMEFRAMES_V3


st.set_page_config(page_title="AutoTrader V3 · PriceGauger", page_icon="🤖", layout="wide")
st.title("AutoTrader V3")
st.caption("Én grunnstrategi + periode + uavhengige modifiers. Adaptive/AI-lag velger eller produserer target; Risk + Execution beholder siste ord.")

enrollments = tuple(item for item in load_active_strategy_enrollments_v2() if item.enabled)
if not enrollments:
    st.info("Ingen aktiv trader-boundary er tilgjengelig ennå.")
    st.stop()

labels = {
    item.pilot_key: f"{item.market_name or item.pilot_key} · {item.account_id} · UIC {item.uic}"
    for item in enrollments
}
trader_id = st.selectbox("Trader", tuple(labels), format_func=lambda key: labels[key], key="v3-control-trader")
config = load_autotrader_config_v3(trader_id)
armed = live_authority_armed_v3(trader_id)

status_col, mode_col, authority_col = st.columns(3)
status_col.metric("V3 config", "AKTIV")
mode_col.metric("Kontrollmodus", config.control_mode)
authority_col.metric("LIVE authority", "ON" if armed else "OFF")

control_tab, chart_tab, sim_tab, audit_tab = st.tabs(("Kontroll", "Chart", "SIM / Adapt", "Audit"))

with control_tab:
    st.subheader("Beslutningskjede")
    st.caption("Velg grunnstrategien først. Periode og modifiers er separate lag og skaper ikke nye strategi-identiteter.")

    strategy_keys = tuple(item.key for item in STRATEGIES_V3)
    strategy_key = st.selectbox(
        "Grunnstrategi",
        strategy_keys,
        index=strategy_keys.index(config.strategy_key),
        format_func=lambda key: next(item.label for item in STRATEGIES_V3 if item.key == key),
        key=f"v3-strategy:{trader_id}",
    )
    strategy_spec = next(item for item in STRATEGIES_V3 if item.key == strategy_key)
    st.caption(strategy_spec.description)

    timeframe = st.selectbox(
        "Periode",
        TIMEFRAMES_V3,
        index=TIMEFRAMES_V3.index(config.timeframe),
        key=f"v3-timeframe:{trader_id}",
        help="Adaptiv lar timeframe-selector/regime-laget velge periode fra observerte data.",
    )
    if timeframe == "Adaptiv":
        st.info("Adaptiv periode er valgt. Runtime-kontrakten kobles til regime/timeframe-selector i neste lag; ingen skjult fallback til fast periode.")

    st.markdown("#### Modifiers")
    st.caption("Bryterne er ortogonale til grunnstrategien. ⚙-innstillinger legges per modifier uten å lage kombinasjonsstrategier.")
    enabled: list[str] = []
    for spec in MODIFIERS_V3:
        c1, c2 = st.columns([5, 1])
        on = c1.toggle(
            spec.label,
            value=spec.key in config.modifiers,
            key=f"v3-mod:{trader_id}:{spec.key}",
            help=spec.description,
        )
        with c2:
            with st.popover("⚙", disabled=not on, help=f"Innstillinger for {spec.label}"):
                settings = load_modifier_settings_v3(trader_id, spec.key)
                edited = dict(settings)
                if spec.key == "impulse":
                    edited["sensitivity"] = st.number_input("Sensitivitet", 0.1, 5.0, float(settings["sensitivity"]), 0.1, key=f"v3-set-imp-s:{trader_id}")
                    edited["max_boost"] = st.number_input("Maks target-multiplikator", 1.0, 5.0, float(settings["max_boost"]), 0.1, key=f"v3-set-imp-b:{trader_id}")
                elif spec.key == "reversal":
                    edited["confirmation_bars"] = st.number_input("Bekreftelsesbars", 1, 20, int(settings["confirmation_bars"]), 1, key=f"v3-set-rev-c:{trader_id}")
                    edited["strength"] = st.number_input("Styrke", 0.1, 3.0, float(settings["strength"]), 0.1, key=f"v3-set-rev-s:{trader_id}")
                elif spec.key == "take-profit":
                    edited["giveback_pct"] = st.number_input("Giveback %", 1.0, 95.0, float(settings["giveback_pct"]), 1.0, key=f"v3-set-tp-g:{trader_id}")
                    edited["min_peak_profit_pct"] = st.number_input("Min peak %", 0.0, 100.0, float(settings["min_peak_profit_pct"]), 0.05, key=f"v3-set-tp-p:{trader_id}")
                    edited["reentry_cooldown_seconds"] = st.number_input("Re-entry pause (s)", 0, 3600, int(settings["reentry_cooldown_seconds"]), 5, key=f"v3-set-tp-r:{trader_id}")
                elif spec.key == "whipsaw":
                    edited["lookback_bars"] = st.number_input("Lookback bars", 3, 200, int(settings["lookback_bars"]), 1, key=f"v3-set-wh-l:{trader_id}")
                    edited["max_direction_changes"] = st.number_input("Maks retningsskift", 1, 50, int(settings["max_direction_changes"]), 1, key=f"v3-set-wh-m:{trader_id}")
                    edited["cooldown_bars"] = st.number_input("Cooldown bars", 0, 50, int(settings["cooldown_bars"]), 1, key=f"v3-set-wh-c:{trader_id}")
                elif spec.key == "regime":
                    edited["lookback_bars"] = st.number_input("Lookback bars", 5, 500, int(settings["lookback_bars"]), 1, key=f"v3-set-reg-l:{trader_id}")
                    edited["trend_threshold"] = st.number_input("Trendterskel", 0.0, 1.0, float(settings["trend_threshold"]), 0.05, key=f"v3-set-reg-t:{trader_id}")
                if edited != settings and st.button("Lagre", key=f"v3-set-save:{trader_id}:{spec.key}", width="stretch"):
                    save_modifier_settings_v3(trader_id, spec.key, edited)
                    st.success("Lagret")
                    st.rerun()
        if on:
            enabled.append(spec.key)

    st.markdown("#### Kontrollmodus")
    control_mode = st.radio(
        "Hvem bestemmer target?",
        CONTROL_MODES_V3,
        index=CONTROL_MODES_V3.index(config.control_mode),
        horizontal=True,
        key=f"v3-mode:{trader_id}",
    )
    descriptions = {
        "Manuell": "Valgt strategi + periode + modifiers produserer target.",
        "Sim-Adapt": "Velger blant parallelle SIM-varianter etter vedvarende relativ prestasjon.",
        "Overseer": "AI velger strategi, periode, modifiers og parametere fra helhetstilstanden.",
        "God Mode": "AI produserer TargetInventory direkte; Risk Governor og Execution kan fortsatt begrense/avvise target.",
    }
    st.caption(descriptions[control_mode])

    desired = AutoTraderConfigV3(
        trader_id=trader_id,
        strategy_key=strategy_key,
        timeframe=timeframe,
        control_mode=control_mode,
        modifiers=tuple(enabled),
    )
    if desired != config:
        if st.button("Lagre V3-oppsett", type="primary", width="stretch", key=f"v3-save:{trader_id}"):
            save_autotrader_config_v3(desired)
            st.success("V3-oppsettet er lagret.")
            st.rerun()
    else:
        st.caption("Oppsettet er lagret.")

with chart_tab:
    st.info("V3-chart kobles til den rene Saxo chart-kjeden. Inntil det flyttes inn her kan Live Chart brukes som isolert datatest.")
    st.page_link("pages/0_Live_Chart.py", label="Åpne Live Chart", icon="📈")

with sim_tab:
    st.subheader("SIM / Adapt")
    st.caption("Her bygges parallelle strategy × timeframe × modifier-varianter, rolling score, hysterese og cooldown. SIM-Adapt får aldri ordreautoritet direkte.")

with audit_tab:
    st.subheader("Beslutningsaudit")
    st.code(
        "market state → base strategy → timeframe → modifiers → AI/adapt → risk governor → target inventory → execution → Saxo",
        language=None,
    )
    st.caption("Alle transformasjoner skal logges med input, output og reason før LIVE-authority utvides.")
