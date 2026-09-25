from __future__ import annotations

import streamlit as st
from datetime import datetime, timezone

from autotrader_fast_live_runtime_v2 import load_fast_live_state_v2

from autotrader_entry_sizing_policy_v2 import (
    SIZING_MODE_FIXED,
    SIZING_MODE_MAX,
    load_entry_sizing_policy_v2,
    save_entry_sizing_policy_v2,
)
from autotrader_live_close_v1 import LiveCloseConfigV1, save_live_close_config_v1
from autotrader_live_open_v2 import LiveOpenConfigV2, save_live_open_config_v2
from autotrader_manage_control_v1 import (
    auto_manage_enabled_v1,
    position_management_enabled_v1,
    set_auto_manage_enabled_v1,
    set_position_management_enabled_v1,
)
from autotrader_managed_positions_v1 import is_position_managed_v1, stop_managing_position_v1
from autotrader_modifier_authority_v1 import modifier_enabled_v1
from autotrader_manual_entry_adoption_v2 import adopt_user_confirmed_position_v2
from autotrader_manual_target_v2 import (
    TARGET_PENDING,
    load_manual_target_quote_v2,
    load_manual_target_state_v2,
    request_manual_target_v2,
)
from autotrader_pilot_equity_v2 import (
    DEFAULT_PILOT_SEED_CAPITAL,
    load_pilot_equity_v2,
    set_pilot_capital_allocation_v2,
)
from autotrader_risk_control_v2 import PositionObservationV2, _position_observations_v2
from autotrader_strategy_catalog_v2 import AUTOTRADER_STRATEGIES_V2, strategy_spec_v2
from autotrader_strategy_enrollment_v2 import (
    ENTRY_MODE_AUTO,
    EXECUTION_MODE_LIVE,
    StrategyEnrollmentV2,
    enroll_strategy_position_v2,
    load_active_strategy_enrollments_v2,
    load_strategy_enrollment_v2,
    set_entry_mode_v2,
)
from autotrader_strategy_switch_v2 import switch_live_strategy_v2
from autotrader_strategy_family_v1 import (
    FAMILY_MACD_STRATEGY_V1,
    FAMILY_PRICE_MACD_STRATEGY_V1,
    strategy_instance_label_v1,
)
from autotrader_take_profit_modifier_v1 import (
    TakeProfitConfigV1,
    load_take_profit_config_v1,
    load_take_profit_state_v1,
    save_take_profit_config_v1,
)
from saxo_provider import LIVE_BASE_URL, configured_client
from trading_desk_v2_context import TradingDeskV2Context
from tradingdesk_strategy_family_ui_v1 import render_strategy_family_builder_v1
from autotrader_v3_macd_trailing_v1 import STRATEGY_KEY_V3
from autotrader_v3_live_authority_v1 import live_authority_armed_v3, set_live_authority_v3
from autotrader_v3_sim_authority_v1 import set_sim_authority_v3
from database import connect


def _account_info(client, account_id: str) -> tuple[str, str]:
    payload = client._get("port/v1/accounts/me")
    rows = payload.get("Data") or []
    if not isinstance(rows, list):
        raise RuntimeError("Saxo account list had invalid format")
    for row in rows:
        if not isinstance(row, dict) or str(row.get("AccountId") or "") != str(account_id):
            continue
        key = str(row.get("AccountKey") or "").strip()
        currency = str(row.get("Currency") or "").strip().upper()
        if key and currency:
            return key, currency
    raise RuntimeError("could not resolve Saxo account")


def _active_live_for_context_v1(context: TradingDeskV2Context) -> StrategyEnrollmentV2 | None:
    matches = tuple(
        item
        for item in load_active_strategy_enrollments_v2()
        if item.execution_mode == EXECUTION_MODE_LIVE
        and item.enabled
        and int(item.market_id) == int(context.market_id)
        and (context.instrument_id is None or int(item.instrument_id) == int(context.instrument_id))
    )
    if len(matches) > 1:
        raise RuntimeError("more than one active LIVE AutoManager controller matched this TradingDesk product")
    return matches[0] if matches else None


def _exact_observation_v1(
    enrollment: StrategyEnrollmentV2,
    observations: tuple[PositionObservationV2, ...],
) -> PositionObservationV2 | None:
    matches = tuple(
        item
        for item in observations
        if item.account_id == enrollment.account_id
        and int(item.uic) == int(enrollment.uic)
        and item.asset_type == enrollment.asset_type
    )
    if len(matches) > 1:
        raise RuntimeError("multiple Saxo positions matched the active AutoManager product")
    return matches[0] if matches else None


def _same_position_basis_v1(left: PositionObservationV2, right: PositionObservationV2) -> bool:
    """The user's confirmation applies only to the exact Saxo basis shown on screen."""
    return (
        left.account_id == right.account_id
        and int(left.uic) == int(right.uic)
        and left.asset_type == right.asset_type
        and bool(left.net_position_id)
        and left.net_position_id == right.net_position_id
        and left.direction == right.direction
        and abs(float(left.amount) - float(right.amount)) <= 1e-9
        and abs(float(left.average_open_price) - float(right.average_open_price)) <= 1e-9
    )


def _v3_runtime_state_v1(trader_id: str):
    try:
        with connect() as db:
            row=db.execute("SELECT status,detail,updated_at FROM autotrader_v3_live_runtime_state WHERE trader_id=?",(trader_id,)).fetchone()
        if row is None: return None
        return (str(row["status"] if isinstance(row,dict) else row[0]),str((row["detail"] if isinstance(row,dict) else row[1]) or ""),str(row["updated_at"] if isinstance(row,dict) else row[2]))
    except Exception:
        return None


def _direction_v1(observation: PositionObservationV2 | None) -> str:
    if observation is None:
        return "FLAT"
    return "LONG" if observation.direction.strip().lower() == "buy" else "SHORT"


def _ensure_execution_ready_v1(enrollment: StrategyEnrollmentV2) -> StrategyEnrollmentV2:
    """AUTO means OPEN and CLOSE are normal runtime capabilities, not extra UX gates."""
    current = enrollment
    if current.entry_mode != ENTRY_MODE_AUTO or not current.live_open_armed:
        current = set_entry_mode_v2(current.pilot_key, ENTRY_MODE_AUTO)
    save_live_open_config_v2(LiveOpenConfigV2(armed=True))
    save_live_close_config_v1(LiveCloseConfigV1(armed=True))
    return current


def _required_directions_v1(enrollment: StrategyEnrollmentV2) -> tuple[str, ...]:
    spec = strategy_spec_v2(enrollment.strategy_key)
    result: list[str] = []
    if spec.can_long:
        result.append("LONG")
    if spec.can_short:
        result.append("SHORT")
    return tuple(result)


def _queue_strategy_switch_v1(selector_key: str, pending_key: str) -> None:
    """Record strategy authority only from an actual selectbox change event."""
    selected = str(st.session_state.get(selector_key) or "").strip()
    if selected:
        st.session_state[pending_key] = selected


def _render_optional_settings_v1(enrollment: StrategyEnrollmentV2, client) -> None:
    """Optional tuning stays hidden from the normal BUY/SELL/manage path."""
    try:
        account_key, currency = _account_info(client, enrollment.account_id)
        equity = load_pilot_equity_v2(pilot_key=enrollment.pilot_key)
    except Exception as exc:
        st.caption(f"Innstillinger venter: {exc}")
        return

    st.caption(
        f"Pilotkapital tildelt {equity.allocated_capital:.2f} {currency} · "
        f"realisert P/L {equity.realized_net_pnl:+.2f} · entry-budget {equity.entry_budget:.2f}"
    )
    allocation = st.number_input(
        "Kapital tildelt AutoTrader",
        min_value=1.0,
        value=float(equity.allocated_capital),
        step=100.0,
        format="%.2f",
        key=f"td-simple-capital-allocation:{enrollment.pilot_key}",
        help="Eksplisitt kapitalgrense for nye entries. All-in bruker maksimalt denne kapitalen + realisert P/L; resten av Saxo-kontoen er utenfor pilotens authority.",
    )
    if abs(float(allocation) - float(equity.allocated_capital)) > 1e-9:
        if st.button("Lagre kapitalallokering", key=f"td-simple-capital-allocation-save:{enrollment.pilot_key}", width="stretch"):
            set_pilot_capital_allocation_v2(
                pilot_key=enrollment.pilot_key,
                capital_allocation=float(allocation),
            )
            st.success("Kapitalallokeringen er oppdatert. Neste OPEN bruker den nye rammen.")
            st.rerun()
    directions = _required_directions_v1(enrollment)
    policies = {
        direction: load_entry_sizing_policy_v2(
            account_key=account_key,
            uic=enrollment.uic,
            asset_type=enrollment.asset_type,
            direction=direction,
        )
        for direction in directions
    }
    persisted_all_in = bool(policies) and all(item.sizing_mode == SIZING_MODE_MAX for item in policies.values())
    key = f"td-simple-all-in:{enrollment.account_id}:{enrollment.uic}:{enrollment.asset_type}"
    if key not in st.session_state:
        st.session_state[key] = persisted_all_in
    selected_all_in = st.toggle(
        "All-in ved ny strategi-entry",
        key=key,
        help="Bruker størst lovlige amount innen pilotens eksisterende Margin Envelope; final Saxo-precheck gjelder fortsatt.",
    )
    if selected_all_in and not persisted_all_in:
        for direction in directions:
            save_entry_sizing_policy_v2(
                account_key=account_key,
                uic=enrollment.uic,
                asset_type=enrollment.asset_type,
                direction=direction,
                sizing_mode=SIZING_MODE_MAX,
            )
        st.success("All-in er aktiv innen pilotrammen.")
        st.rerun()
    elif not selected_all_in:
        fixed_values: dict[str, float] = {}
        for direction, policy in policies.items():
            default = float(policy.fixed_amount or 0.01)
            fixed_values[direction] = st.number_input(
                f"{direction} amount",
                min_value=0.00000001,
                value=default,
                step=0.01,
                format="%.8f",
                key=f"td-simple-fixed:{enrollment.pilot_key}:{direction}",
            )
        if st.button("Lagre fast amount", key=f"td-simple-fixed-save:{enrollment.pilot_key}", width="stretch"):
            for direction, amount in fixed_values.items():
                save_entry_sizing_policy_v2(
                    account_key=account_key,
                    uic=enrollment.uic,
                    asset_type=enrollment.asset_type,
                    direction=direction,
                    sizing_mode=SIZING_MODE_FIXED,
                    fixed_amount=amount,
                )
            st.success("Fast amount er lagret; Saxo revaliderer før hver ordre.")
            st.rerun()
    _render_take_profit_settings_v1(enrollment)
    st.page_link("pages/6_AutoTrader_POC.py", label="Avanserte AutoTrader-detaljer", icon="⚙️")


def _render_take_profit_settings_v1(enrollment: StrategyEnrollmentV2) -> None:
    if not modifier_enabled_v1("take_profit"):
        st.caption("X + TakeProfit er AV globalt. Aktiver under AutoTrader v2 → Automatiske tillegg for å bruke den.")
        return
    try:
        config = load_take_profit_config_v1(enrollment.pilot_key)
        state = load_take_profit_state_v1(enrollment.pilot_key)
    except Exception as exc:
        st.caption(f"TakeProfit venter: {exc}")
        return

    st.divider()
    st.markdown("**X + TakeProfit**")
    st.caption(
        "Generisk wrapper rundt aktiv strategi. Peak-profit (MFE) spores på faktisk Saxo-posisjon; "
        "ved valgt relativ giveback går wrapperen FLAT gjennom vanlig CLOSE-livssyklus."
    )

    enabled = st.toggle(
        "TakeProfit aktiv",
        value=bool(config.enabled),
        key=f"td-tp-enabled:{enrollment.pilot_key}",
    )
    giveback = st.number_input(
        "Tillatt tilbakegang av peak-profit (%)",
        min_value=1.0,
        max_value=95.0,
        value=float(config.giveback_pct),
        step=1.0,
        format="%.1f",
        disabled=not enabled,
        key=f"td-tp-giveback:{enrollment.pilot_key}",
        help="Eksempel: peak +1.00 %, giveback 10 % → FLAT-gulv ca. +0.90 %.",
    )
    min_peak = st.number_input(
        "Aktiver først etter gevinst ≥ (%)",
        min_value=0.0,
        max_value=100.0,
        value=float(config.min_peak_profit_pct),
        step=0.05,
        format="%.2f",
        disabled=not enabled,
        key=f"td-tp-min-peak:{enrollment.pilot_key}",
        help="Hindrer at mikroskopisk positiv P/L og spread-støy armer TakeProfit.",
    )
    cooldown = st.number_input(
        "Re-entry pause etter TakeProfit (sek)",
        min_value=0,
        max_value=3600,
        value=int(config.reentry_cooldown_seconds),
        step=5,
        disabled=not enabled,
        key=f"td-tp-cooldown:{enrollment.pilot_key}",
    )
    if st.button(
        "Lagre TakeProfit",
        key=f"td-tp-save:{enrollment.pilot_key}",
        width="stretch",
    ):
        try:
            save_take_profit_config_v1(
                enrollment.pilot_key,
                TakeProfitConfigV1(
                    enabled=bool(enabled),
                    giveback_pct=float(giveback),
                    min_peak_profit_pct=float(min_peak),
                    reentry_cooldown_seconds=int(cooldown),
                ),
            )
        except Exception as exc:
            st.error(f"TakeProfit kunne ikke lagres: {exc}")
        else:
            st.success("TakeProfit-innstillingene er lagret.")
            st.rerun()

    if state is not None:
        peak = float(state.get("high_water_pct") or 0.0)
        floor = state.get("floor_pct")
        current = float(state.get("current_pnl_pct") or 0.0)
        status = "TRIGGET" if state.get("triggered_at") else ("ARMERT" if state.get("armed") else "venter")
        floor_text = "—" if floor is None else f"{float(floor):+.3f}%"
        st.caption(
            f"TakeProfit {status} · nå {current:+.3f}% · peak {peak:+.3f}% · gulv {floor_text}"
        )


def _bootstrap_candidate_v1(
    context: TradingDeskV2Context,
    observations: tuple[PositionObservationV2, ...],
) -> PositionObservationV2 | None:
    if context.instrument is None:
        return None
    expected_uic = int(context.instrument.provider_instrument_id)
    expected_asset = str(context.instrument.asset_type or "")
    matches = tuple(
        item for item in observations
        if int(item.uic) == expected_uic and item.asset_type == expected_asset
    )
    if len(matches) > 1:
        raise RuntimeError("multiple Saxo positions matched first AutoManager bootstrap")
    return matches[0] if matches else None


def render_tradingdesk_automanager_simple_v1(
    context: TradingDeskV2Context,
) -> tuple[PositionObservationV2, ...] | None:
    """Simple control plane: BUY, SELL and one LIVE strategy authority."""
    client = configured_client()
    if client is None or client.base_url.rstrip("/").lower() != LIVE_BASE_URL.lower():
        st.info("Saxo LIVE er ikke tilgjengelig.")
        return None

    try:
        observations = _position_observations_v2(client)
        enrollment = _active_live_for_context_v1(context)
    except Exception as exc:
        st.warning(f"AutoManager kunne ikke lese LIVE-state: {exc}")
        return None

    st.markdown("**Posisjon og AutoTrade**")

    if enrollment is None:
        bootstrap = _bootstrap_candidate_v1(context, observations)
        selected = st.selectbox(
            "Strategi",
            AUTOTRADER_STRATEGIES_V2,
            format_func=lambda item: item.label,
            key=f"td-simple-bootstrap-strategy:{context.market_id}",
        )
        st.caption("Ingen aktiv LIVE-controller på dette produktet.")
        if bootstrap is None:
            st.info("Første bootstrap trenger foreløpig en eksisterende Saxo-posisjon. Etter bootstrap kan BUY/SELL brukes direkte fra PriceGauger.")
            return observations
        start = st.button("Start · Manage + AutoTrade", type="primary", key=f"td-simple-bootstrap:{context.market_id}", width="stretch")
        if start:
            try:
                _, currency = _account_info(client, bootstrap.account_id)
                enrollment, _ = enroll_strategy_position_v2(
                    bootstrap,
                    strategy_key=selected.key,
                    execution_mode=EXECUTION_MODE_LIVE,
                    seed_capital=float(DEFAULT_PILOT_SEED_CAPITAL),
                    currency=currency,
                    entry_mode=ENTRY_MODE_AUTO,
                )
                _ensure_execution_ready_v1(enrollment)
                set_position_management_enabled_v1(enrollment, True)
                if not is_position_managed_v1(bootstrap):
                    adopt_user_confirmed_position_v2(enrollment, bootstrap)
                set_auto_manage_enabled_v1(enrollment, True)
            except Exception as exc:
                st.error(f"LIVE-controller kunne ikke startes: {exc}")
            else:
                st.rerun()
        return observations

    observation = _exact_observation_v1(enrollment, observations)
    observed_direction = _direction_v1(observation)
    auto_trade_enabled = auto_manage_enabled_v1(enrollment)
    position_manage_enabled = position_management_enabled_v1(enrollment)

    # Engine selection is a first-class operator choice, separate from ON/OFF.
    engine_v3 = enrollment.strategy_key == STRATEGY_KEY_V3
    engine_choice = st.radio(
        "AutoTrader-motor",
        ("V2", "V3"),
        index=1 if engine_v3 else 0,
        horizontal=True,
        key=f"td-engine-select:{enrollment.account_id}:{enrollment.uic}:{enrollment.asset_type}",
        help="Velg hvilken motor som eier AutoTraderen. ON/OFF under gjelder den valgte motoren.",
    )
    requested_v3 = engine_choice == "V3"
    if requested_v3 != engine_v3:
        try:
            source_key = enrollment.pilot_key
            result = switch_live_strategy_v2(
                pilot_key=source_key,
                target_strategy_key=STRATEGY_KEY_V3 if requested_v3 else FAMILY_MACD_STRATEGY_V1,
            )
            switched = load_strategy_enrollment_v2(result.to_pilot_key)
            if switched is None:
                raise RuntimeError("engine switch did not persist target enrollment")
            # Transfer operator authority to the selected engine; never leave both engines armed.
            if requested_v3:
                set_position_management_enabled_v1(switched, False)
                set_auto_manage_enabled_v1(switched, False)
                set_sim_authority_v3(source_key, False)
                set_live_authority_v3(source_key, False)
                set_sim_authority_v3(switched.pilot_key, False)
                set_live_authority_v3(switched.pilot_key, True)
            else:
                set_live_authority_v3(source_key, False)
                set_sim_authority_v3(source_key, False)
                set_live_authority_v3(switched.pilot_key, False)
                _ensure_execution_ready_v1(switched)
                set_position_management_enabled_v1(switched, True)
                set_auto_manage_enabled_v1(switched, True)
        except Exception as exc:
            st.error(f"Motorbytte kunne ikke fullføres: {exc}")
        else:
            st.rerun()

    # One obvious master authority control. Engine identity is explicit so V2 and V3
    # can coexist without an ARMED badge from one engine being mistaken for the other.
    if engine_v3:
        engine_on = live_authority_armed_v3(enrollment.pilot_key)
        engine_label = "ENGINE V3 · LIVE"
    else:
        engine_on = bool(position_manage_enabled and auto_trade_enabled)
        engine_label = "ENGINE V2 · LIVE"
    needs_takeover = not engine_v3 and observation is not None and not is_position_managed_v1(observation)
    if needs_takeover:
        st.error("V2 er pauset: Saxo-posisjonen har ikke en bekreftet PriceGauger-basis. En omstart eller LIVE ON løser ikke dette.")
        st.caption(
            f"Saxo {observed_direction} {observation.amount:g} · konto {enrollment.account_id} · "
            f"UIC {enrollment.uic} · {enrollment.asset_type} · posisjon {observation.net_position_id}"
        )
        st.caption("Bekreft bare hvis dette er posisjonen du vil at V2 skal forvalte. Bekreftelsen sender ingen ordre; slå LIVE ON etterpå.")
        if st.button("Bekreft og overta Saxo-posisjon", key=f"td-confirm-position:{enrollment.pilot_key}"):
            try:
                fresh = _exact_observation_v1(enrollment, _position_observations_v2(client))
                if fresh is None or not _same_position_basis_v1(observation, fresh):
                    raise RuntimeError("Saxo-posisjonen endret seg. Oppdater siden og kontroller den på nytt.")
                adopt_user_confirmed_position_v2(enrollment, fresh)
            except Exception as exc:
                st.error(f"Posisjonen kunne ikke overtas: {exc}")
            else:
                st.success("Posisjonen er bekreftet. V2 kan nå slås på med LIVE-bryteren.")
                st.rerun()
    desired_engine_on = st.toggle(
        f"{engine_label} · {'ON' if engine_on else 'OFF'}",
        value=engine_on,
        disabled=needs_takeover and not engine_on,
        key=f"td-engine-master:{enrollment.pilot_key}",
        help="Master authority. ON betyr at valgt motor faktisk forvalter denne Saxo-boundaryen; OFF betyr ingen authority.",
    )
    if desired_engine_on != engine_on:
        try:
            if engine_v3:
                set_live_authority_v3(enrollment.pilot_key, desired_engine_on)
            else:
                set_position_management_enabled_v1(enrollment, desired_engine_on)
                set_auto_manage_enabled_v1(enrollment, desired_engine_on)
        except Exception as exc:
            st.error(f"{engine_label} kunne ikke {'startes' if desired_engine_on else 'stoppes'}: {exc}")
        else:
            st.rerun()

    try:
        account_key, _ = _account_info(client, enrollment.account_id)
        quote = load_manual_target_quote_v2(enrollment, account_key=account_key)
        quote_error = None
    except Exception as exc:
        quote = None
        quote_error = str(exc)

    target_state = load_manual_target_state_v2(enrollment.pilot_key)
    if target_state is not None and target_state.status == TARGET_PENDING:
        st.info(f"Brukermål pågår: {target_state.target_direction} · execution fullfører CLOSE → FLAT → OPEN.")

    buy_col, sell_col = st.columns(2, gap="small")
    buy_label = "BUY" if quote is None else f"BUY @ {quote.ask:,.2f}".replace(",", " ")
    sell_label = "SELL" if quote is None else f"SELL @ {quote.bid:,.2f}".replace(",", " ")
    buy = buy_col.button(
        buy_label,
        type="primary" if observed_direction != "LONG" else "secondary",
        disabled=quote is None or observed_direction == "LONG",
        key=f"td-simple-buy:{enrollment.account_id}:{enrollment.uic}:{enrollment.asset_type}",
        width="stretch",
    )
    sell = sell_col.button(
        sell_label,
        type="primary" if observed_direction != "SHORT" else "secondary",
        disabled=quote is None or observed_direction == "SHORT",
        key=f"td-simple-sell:{enrollment.account_id}:{enrollment.uic}:{enrollment.asset_type}",
        width="stretch",
    )
    if quote_error:
        st.caption(f"BUY/SELL venter på Saxo-pris: {quote_error}")

    if buy or sell:
        target = "LONG" if buy else "SHORT"
        try:
            enrollment = _ensure_execution_ready_v1(enrollment)
            result = request_manual_target_v2(enrollment, target_direction=target)
        except Exception as exc:
            st.error(f"{target}-målet kunne ikke settes: {exc}")
        else:
            if result.already_observed:
                st.success(f"Saxo er allerede {target}; execution-basen er synkronisert.")
            elif result.request_created:
                st.success(f"Mål satt: {target}. Execution-motoren har overtatt overgangen.")
            else:
                st.success(f"Mål satt: {target}. Execution fortsetter på neste syklus.")
            st.rerun()

    # Strategy controls are engine-specific. Never render V2 family controls while
    # ENGINE V3 owns the boundary: that made the selected behavior ambiguous.
    if engine_v3:
        # TradingDesk is deliberately only the cockpit summary for V3.
        # Strategy/timeframe/modifier/AI configuration belongs on the dedicated
        # AutoTrader V3 page so this surface cannot grow into a second control plane.
        with st.container(border=True):
            st.markdown("**AutoTrader V3**")
            runtime = _v3_runtime_state_v1(enrollment.pilot_key) if engine_on else None
            status_col, position_col = st.columns(2, gap="small")
            status_col.metric("Motor", "ON" if engine_on else "OFF")
            position_col.metric("Saxo", observed_direction)
            if not engine_on:
                st.caption("V3 authority er av.")
            elif runtime is None:
                st.error("LIVE ARMED · NOT MANAGING / ingen worker-heartbeat")
            elif runtime[0] == "MANAGING":
                st.success(f"LIVE MANAGING · {runtime[1]} · heartbeat {runtime[2]}")
            else:
                st.warning(f"LIVE {runtime[0]} · {runtime[1]} · heartbeat {runtime[2]}")
            st.caption("Strategi, periode, modifiers, SIM-Adapt, Overseer og God Mode styres i den dedikerte V3-kontrollflaten.")
        return observations

    strategy_col, settings_col = st.columns([3.55, 0.45], gap="small")
    strategy_selector_key = (
        f"td-simple-strategy:{enrollment.account_id}:{enrollment.uic}:{enrollment.asset_type}"
    )
    strategy_pending_key = f"{strategy_selector_key}:pending"
    strategy_error_key = f"{strategy_selector_key}:error"
    family_primary_keys = {FAMILY_MACD_STRATEGY_V1, FAMILY_PRICE_MACD_STRATEGY_V1}
    strategy_keys = tuple(item.key for item in AUTOTRADER_STRATEGIES_V2 if item.key not in family_primary_keys)
    pending_strategy_key = str(st.session_state.get(strategy_pending_key) or "").strip()
    if strategy_selector_key not in st.session_state or not pending_strategy_key:
        if str(st.session_state.get(strategy_selector_key) or "") != enrollment.strategy_key:
            st.session_state[strategy_selector_key] = enrollment.strategy_key
    strategy_error = st.session_state.pop(strategy_error_key, None)
    if strategy_error:
        st.error(f"Strategien kunne ikke byttes: {strategy_error}")
    with strategy_col:
        family_label = strategy_instance_label_v1(pilot_key=enrollment.pilot_key, strategy_key=enrollment.strategy_key)
        authority = "AKTIV" if (position_manage_enabled and auto_trade_enabled) else "AV"
        st.caption(f"LIVE {authority} · {family_label or strategy_spec_v2(enrollment.strategy_key).label}")
    with settings_col:
        with st.popover("⚙", width="stretch"):
            st.markdown("**Legacy / enkeltstrategi**")
            st.selectbox("Strategi", strategy_keys, index=None, format_func=lambda key: strategy_spec_v2(key).label, key=strategy_selector_key, on_change=_queue_strategy_switch_v1, args=(strategy_selector_key, strategy_pending_key), label_visibility="collapsed")
            st.divider()
            st.markdown("**Valgfritt**")
            _render_optional_settings_v1(enrollment, client)
    with st.container(border=True):
        render_strategy_family_builder_v1(enrollment=enrollment, instrument_id=int(enrollment.instrument_id))

    requested_strategy_key = str(st.session_state.pop(strategy_pending_key, "") or "").strip()
    if requested_strategy_key and requested_strategy_key != enrollment.strategy_key:
        try:
            result = switch_live_strategy_v2(
                pilot_key=enrollment.pilot_key,
                target_strategy_key=requested_strategy_key,
            )
            switched = load_strategy_enrollment_v2(result.to_pilot_key)
            if switched is not None:
                _ensure_execution_ready_v1(switched)
        except Exception as exc:
            # The selector widget has already been instantiated in this run, so its
            # state cannot safely be rewritten here. Carry the error across one rerun;
            # the next ordinary render resyncs the selector from backend truth.
            st.session_state[strategy_error_key] = str(exc)
            st.rerun()
        else:
            st.rerun()

    spec = strategy_spec_v2(enrollment.strategy_key)
    family_label = strategy_instance_label_v1(
        pilot_key=enrollment.pilot_key,
        strategy_key=enrollment.strategy_key,
    )
    live_status = "AKTIV" if (position_manage_enabled and auto_trade_enabled) else "AV"
    st.caption(
        f"Nå {observed_direction} · LIVE {live_status} · "
        f"Aktiv strategi (backend): {family_label or spec.label}"
    )

    # Read-only LIVE observability. This deliberately reads the same durable state
    # that the strategy runtimes persist; it has no execution or strategy authority.
    try:
        runtime_state = load_fast_live_state_v2(enrollment)
    except Exception as exc:
        st.caption(f"LIVE runtime-state venter: {exc}")
    else:
        if live_status != "AKTIV":
            st.caption("LIVE runtime: AV — ingen strategi har ordreautoritet.")
        elif runtime_state is None:
            st.warning("LIVE runtime: ingen persistert strategi-evaluering ennå.")
        else:
            evaluated_at = runtime_state.last_action_at
            if evaluated_at is None:
                evaluated_text = "aldri"
                age_text = "ukjent alder"
                stale = True
            else:
                evaluated_utc = evaluated_at.astimezone(timezone.utc)
                age_seconds = max(
                    0.0,
                    (datetime.now(timezone.utc) - evaluated_utc).total_seconds(),
                )
                evaluated_text = evaluated_utc.strftime("%d.%m.%Y %H:%M:%S UTC")
                age_text = f"{age_seconds:.0f}s siden"
                stale = age_seconds > 180.0
            pending = runtime_state.pending_target_direction or "ingen"
            intent = runtime_state.intent_signal or "ingen"
            message = (
                f"LIVE-evaluering: {evaluated_text} ({age_text}) · "
                f"target {runtime_state.desired_direction} · Saxo {observed_direction} · "
                f"pending {pending}"
            )
            if stale and live_status == "AKTIV":
                st.error(message + " · DATA/RUNTIME SER STALE UT")
            else:
                st.caption(message)
            if runtime_state.intent_signal_at is not None or runtime_state.intent_signal:
                signal_at = (
                    "ukjent"
                    if runtime_state.intent_signal_at is None
                    else runtime_state.intent_signal_at.astimezone(timezone.utc).strftime("%d.%m.%Y %H:%M:%S UTC")
                )
                st.caption(f"Siste target-skifte: {signal_at} · {intent}")
    return observations


__all__ = [
    "_active_live_for_context_v1",
    "render_tradingdesk_automanager_simple_v1",
]
