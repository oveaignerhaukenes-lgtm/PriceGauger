from __future__ import annotations

import streamlit as st

from autotrader_entry_sizing_policy_v2 import (
    SIZING_MODE_FIXED,
    SIZING_MODE_MAX,
    load_entry_sizing_policy_v2,
    save_entry_sizing_policy_v2,
)
from autotrader_live_close_v1 import LiveCloseConfigV1, save_live_close_config_v1
from autotrader_live_open_v2 import LiveOpenConfigV2, save_live_open_config_v2
from autotrader_manage_control_v1 import auto_manage_enabled_v1, set_auto_manage_enabled_v1
from autotrader_managed_positions_v1 import is_position_managed_v1
from autotrader_manual_entry_adoption_v2 import adopt_user_confirmed_position_v2
from autotrader_manual_target_v2 import (
    TARGET_PENDING,
    load_manual_target_quote_v2,
    load_manual_target_state_v2,
    request_manual_target_v2,
)
from autotrader_pilot_equity_v2 import DEFAULT_PILOT_SEED_CAPITAL, load_pilot_equity_v2
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
from saxo_provider import LIVE_BASE_URL, configured_client
from trading_desk_v2_context import TradingDeskV2Context


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


def _render_optional_settings_v1(enrollment: StrategyEnrollmentV2, client) -> None:
    """Optional tuning stays hidden from the normal BUY/SELL/manage path."""
    try:
        account_key, currency = _account_info(client, enrollment.account_id)
        equity = load_pilot_equity_v2(pilot_key=enrollment.pilot_key)
    except Exception as exc:
        st.caption(f"Innstillinger venter: {exc}")
        return

    st.caption(f"Pilotkapital {equity.equity:.2f} {currency}")
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
    st.page_link("pages/6_AutoTrader_POC.py", label="Avanserte AutoTrader-detaljer", icon="⚙️")


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
    """Simple control plane: BUY, SELL, Manage position, strategy."""
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

    st.markdown("**Posisjon og AutoManager**")

    if enrollment is None:
        bootstrap = _bootstrap_candidate_v1(context, observations)
        selected = st.selectbox(
            "Strategi",
            AUTOTRADER_STRATEGIES_V2,
            format_func=lambda item: item.label,
            key=f"td-simple-bootstrap-strategy:{context.market_id}",
        )
        st.caption("AutoManager er OFF · ingen aktiv LIVE-controller på dette produktet.")
        if bootstrap is None:
            st.info("Første bootstrap trenger foreløpig en eksisterende Saxo-posisjon. Etter bootstrap kan BUY/SELL brukes direkte fra PriceGauger også når AutoManager er OFF.")
            return observations
        start = st.button("Manage position · ON", type="primary", key=f"td-simple-bootstrap:{context.market_id}", width="stretch")
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
                set_auto_manage_enabled_v1(enrollment, True)
                if not is_position_managed_v1(bootstrap):
                    adopt_user_confirmed_position_v2(enrollment, bootstrap)
            except Exception as exc:
                st.error(f"AutoManager kunne ikke startes: {exc}")
            else:
                st.rerun()
        return observations

    observation = _exact_observation_v1(enrollment, observations)
    observed_direction = _direction_v1(observation)
    manage_enabled = auto_manage_enabled_v1(enrollment)

    try:
        account_key, _ = _account_info(client, enrollment.account_id)
        quote = load_manual_target_quote_v2(enrollment, account_key=account_key)
        quote_error = None
    except Exception as exc:
        quote = None
        quote_error = str(exc)

    target_state = load_manual_target_state_v2(enrollment.pilot_key)
    if target_state is not None and target_state.status == TARGET_PENDING:
        st.info(f"Brukermål pågår: {target_state.target_direction} · AutoManager fullfører CLOSE → FLAT → OPEN.")

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
                st.success(f"Saxo er allerede {target}; AutoManager-basen er synkronisert.")
            elif result.request_created:
                st.success(f"Mål satt: {target}. Execution-motoren har overtatt overgangen.")
            else:
                st.success(f"Mål satt: {target}. Execution fortsetter på neste syklus.")
            st.rerun()

    manage_col, strategy_col, settings_col = st.columns([1.25, 2.2, 0.45], gap="small")
    toggle_key = f"td-simple-manage:{enrollment.account_id}:{enrollment.uic}:{enrollment.asset_type}"
    if toggle_key not in st.session_state:
        st.session_state[toggle_key] = manage_enabled
    with manage_col:
        selected_manage = st.toggle("Manage position", key=toggle_key)
    with strategy_col:
        current_index = next(
            (index for index, item in enumerate(AUTOTRADER_STRATEGIES_V2) if item.key == enrollment.strategy_key),
            0,
        )
        selected_strategy = st.selectbox(
            "Strategi",
            AUTOTRADER_STRATEGIES_V2,
            index=current_index,
            format_func=lambda item: item.label,
            key=f"td-simple-strategy:{enrollment.account_id}:{enrollment.uic}:{enrollment.asset_type}",
            label_visibility="collapsed",
        )
    with settings_col:
        with st.popover("⚙", width="stretch"):
            st.markdown("**Valgfritt**")
            _render_optional_settings_v1(enrollment, client)

    if selected_manage != manage_enabled:
        try:
            if selected_manage:
                enrollment = _ensure_execution_ready_v1(enrollment)
                if observation is not None and not is_position_managed_v1(observation):
                    adopt_user_confirmed_position_v2(enrollment, observation)
            set_auto_manage_enabled_v1(enrollment, selected_manage)
        except Exception as exc:
            st.session_state[toggle_key] = manage_enabled
            st.error(f"Manage position kunne ikke endres: {exc}")
        else:
            st.rerun()

    if selected_strategy.key != enrollment.strategy_key:
        try:
            result = switch_live_strategy_v2(
                pilot_key=enrollment.pilot_key,
                target_strategy_key=selected_strategy.key,
            )
            switched = load_strategy_enrollment_v2(result.to_pilot_key)
            if switched is not None:
                _ensure_execution_ready_v1(switched)
        except Exception as exc:
            st.error(f"Strategien kunne ikke byttes: {exc}")
        else:
            st.rerun()

    # Auto-adoption is a runtime detail, not another user permission.
    if manage_enabled and observation is not None and not is_position_managed_v1(observation):
        try:
            adopt_user_confirmed_position_v2(enrollment, observation)
        except Exception as exc:
            st.caption(f"AutoManager-basis venter: {exc}")

    spec = strategy_spec_v2(enrollment.strategy_key)
    status = "ON" if manage_enabled else "OFF"
    st.caption(f"Nå {observed_direction} · AutoManager {status} · {spec.label}")
    return observations


__all__ = [
    "_active_live_for_context_v1",
    "render_tradingdesk_automanager_simple_v1",
]
