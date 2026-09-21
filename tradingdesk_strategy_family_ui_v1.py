from __future__ import annotations

from dataclasses import dataclass

import streamlit as st

from autotrader_macd_timeframe_live_v1 import LIVE_MACD_CONTROL_STRATEGIES_V1
from autotrader_strategy_enrollment_v2 import StrategyEnrollmentV2, load_strategy_enrollment_v2
from autotrader_strategy_family_v1 import (
    FAMILY_LABELS_V1,
    FAMILY_MACD_V1,
    FAMILY_PRICE_MACD_V1,
    FAMILY_PRICE_STOCH_V1,
    TIMEFRAME_PRESETS_V1,
    family_display_label_v1,
    family_strategy_key_v1,
    load_strategy_family_config_v1,
    reconfigure_live_family_v1,
    save_strategy_family_config_v1,
    strategy_family_v1,
    validate_timeframe_minutes_v1,
)
from autotrader_strategy_switch_v2 import switch_live_strategy_v2


SIM_MODE_V1 = "SIM"
LIVE_MODE_V1 = "LIVE"
RUN_MODES_V1 = (SIM_MODE_V1, LIVE_MODE_V1)
CUSTOM_TIMEFRAME_LABEL_V1 = "Egen…"


@dataclass(frozen=True, slots=True)
class FamilyUiSelectionV1:
    family: str
    timeframe_minutes: int


def sim_family_session_key_v1(instrument_id: int) -> str:
    return f"td-family-sim-v1:{int(instrument_id)}"


def load_sim_family_selection_v1(instrument_id: int) -> FamilyUiSelectionV1 | None:
    raw = st.session_state.get(sim_family_session_key_v1(instrument_id))
    if not isinstance(raw, dict):
        return None
    try:
        family = str(raw["family"])
        minutes = validate_timeframe_minutes_v1(int(raw["timeframe_minutes"]))
    except Exception:
        return None
    return FamilyUiSelectionV1(family=family, timeframe_minutes=minutes)


def _legacy_hint_v1(enrollment: StrategyEnrollmentV2) -> FamilyUiSelectionV1 | None:
    configured_family = strategy_family_v1(enrollment.strategy_key)
    if configured_family is not None:
        config = load_strategy_family_config_v1(
            enrollment.pilot_key,
            strategy_key=enrollment.strategy_key,
        )
        if config is not None:
            return FamilyUiSelectionV1(
                family=config.family,
                timeframe_minutes=int(config.timeframe_minutes),
            )
    if enrollment.strategy_key in LIVE_MACD_CONTROL_STRATEGIES_V1:
        return FamilyUiSelectionV1(
            family=FAMILY_MACD_V1,
            timeframe_minutes=int(LIVE_MACD_CONTROL_STRATEGIES_V1[enrollment.strategy_key]),
        )
    if enrollment.strategy_key == "price-stoch-half-parade-v1":
        return FamilyUiSelectionV1(family=FAMILY_PRICE_STOCH_V1, timeframe_minutes=1)
    return None


def _timeframe_choice_v1(*, base_key: str, family: str, default_minutes: int) -> int:
    if family == FAMILY_PRICE_STOCH_V1:
        st.selectbox(
            "Tidsperiode",
            ("1m",),
            index=0,
            disabled=True,
            key=f"{base_key}:tf-stoch-fixed",
            help="Price + Stoch v1 bruker foreløpig 1m price/stochastic-clock.",
        )
        return 1

    default = int(default_minutes)
    options: tuple[object, ...] = tuple(TIMEFRAME_PRESETS_V1) + (CUSTOM_TIMEFRAME_LABEL_V1,)
    default_option: object = default if default in TIMEFRAME_PRESETS_V1 else CUSTOM_TIMEFRAME_LABEL_V1
    selected = st.selectbox(
        "Tidsperiode",
        options,
        index=options.index(default_option),
        format_func=lambda value: f"{value}m" if isinstance(value, int) else str(value),
        key=f"{base_key}:tf-preset:{family}",
    )
    if selected != CUSTOM_TIMEFRAME_LABEL_V1:
        return int(selected)
    return validate_timeframe_minutes_v1(
        int(
            st.number_input(
                "Egen tidsperiode (min)",
                min_value=1,
                max_value=240,
                value=max(1, min(240, default)),
                step=1,
                key=f"{base_key}:tf-custom:{family}",
            )
        )
    )


def render_strategy_family_builder_v1(
    *,
    enrollment: StrategyEnrollmentV2,
    instrument_id: int,
) -> None:
    """Render family + timeframe + SIM/LIVE activation without implicit mutations."""

    hint = _legacy_hint_v1(enrollment)
    current_sim = load_sim_family_selection_v1(instrument_id)
    initial = current_sim or hint or FamilyUiSelectionV1(
        family=FAMILY_MACD_V1,
        timeframe_minutes=5,
    )

    base_key = f"td-family-builder-v1:{enrollment.account_id}:{enrollment.uic}:{enrollment.asset_type}"
    st.markdown("**Strategifamilie**")
    st.caption(
        "Familie + tidsperiode er strategien. SIM kjører samme policy i Strategy Lab; "
        "LIVE bruker den herdede AutoManager/execution-kjeden."
    )

    family_options = (FAMILY_MACD_V1, FAMILY_PRICE_MACD_V1, FAMILY_PRICE_STOCH_V1)
    family = st.selectbox(
        "Familie",
        family_options,
        index=family_options.index(initial.family) if initial.family in family_options else 0,
        format_func=lambda value: FAMILY_LABELS_V1[value],
        key=f"{base_key}:family",
    )
    minutes = _timeframe_choice_v1(
        base_key=base_key,
        family=family,
        default_minutes=initial.timeframe_minutes if family == initial.family else 1 if family == FAMILY_PRICE_STOCH_V1 else 5,
    )

    active_family = strategy_family_v1(enrollment.strategy_key)
    live_matches = False
    if active_family == family:
        cfg = load_strategy_family_config_v1(
            enrollment.pilot_key,
            strategy_key=enrollment.strategy_key,
        )
        live_matches = bool(cfg is not None and int(cfg.timeframe_minutes) == int(minutes))

    current_sim_matches = bool(
        current_sim is not None
        and current_sim.family == family
        and current_sim.timeframe_minutes == int(minutes)
    )
    default_modes = []
    if current_sim_matches:
        default_modes.append(SIM_MODE_V1)
    if live_matches:
        default_modes.append(LIVE_MODE_V1)
    if not default_modes:
        default_modes = [SIM_MODE_V1]

    modes = st.multiselect(
        "Aktiver i",
        RUN_MODES_V1,
        default=default_modes,
        key=f"{base_key}:modes:{family}:{minutes}",
        help="Velg SIM, LIVE eller begge. Ingen endring skjer før du trykker Bruk.",
    )

    target_label = family_display_label_v1(family, minutes)
    if st.button(
        f"Bruk {target_label}",
        key=f"{base_key}:apply:{family}:{minutes}",
        type="primary",
        width="stretch",
    ):
        if SIM_MODE_V1 in modes:
            st.session_state[sim_family_session_key_v1(instrument_id)] = {
                "family": family,
                "timeframe_minutes": int(minutes),
            }
        else:
            st.session_state.pop(sim_family_session_key_v1(instrument_id), None)

        if LIVE_MODE_V1 in modes:
            target_strategy_key = family_strategy_key_v1(family)
            try:
                if enrollment.strategy_key != target_strategy_key:
                    switched = switch_live_strategy_v2(
                        pilot_key=enrollment.pilot_key,
                        target_strategy_key=target_strategy_key,
                    )
                    target_enrollment = load_strategy_enrollment_v2(switched.to_pilot_key)
                    if target_enrollment is None:
                        raise RuntimeError("family strategy switch did not persist target enrollment")
                    reconfigure_live_family_v1(
                        pilot_key=target_enrollment.pilot_key,
                        family=family,
                        timeframe_minutes=minutes,
                    )
                else:
                    reconfigure_live_family_v1(
                        pilot_key=enrollment.pilot_key,
                        family=family,
                        timeframe_minutes=minutes,
                    )
            except Exception as exc:
                st.error(f"Familie/LIVE kunne ikke aktiveres: {exc}")
                return

        if not modes:
            st.info("Ingen kjøremodus valgt; SIM-selection er fjernet og LIVE er ikke endret.")
        st.rerun()

    sim_text = (
        family_display_label_v1(current_sim.family, current_sim.timeframe_minutes)
        if current_sim is not None
        else "av"
    )
    if hint is None:
        live_text = f"Legacy: {enrollment.strategy_key}"
    else:
        live_text = family_display_label_v1(hint.family, hint.timeframe_minutes)
    st.caption(f"SIM nå: {sim_text} · LIVE nå: {live_text}")


__all__ = [
    "FamilyUiSelectionV1",
    "LIVE_MODE_V1",
    "RUN_MODES_V1",
    "SIM_MODE_V1",
    "load_sim_family_selection_v1",
    "render_strategy_family_builder_v1",
    "sim_family_session_key_v1",
]
