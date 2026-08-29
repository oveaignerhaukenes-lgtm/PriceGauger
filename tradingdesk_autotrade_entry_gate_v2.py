from __future__ import annotations

from uuid import NAMESPACE_URL, uuid5

import streamlit as st

from autotrader_entry_policy_v2 import (
    is_margin_product_v2,
    load_pilot_margin_config_v2,
    load_product_admission_v2,
    save_pilot_margin_config_v2,
    save_product_admission_v2,
)
from autotrader_live_close_v1 import (
    LiveCloseConfigV1,
    code_gate_enabled_v1 as live_close_code_gate_enabled_v1,
    load_live_close_config_v1,
    save_live_close_config_v1,
)
from autotrader_live_open_v2 import (
    LiveOpenConfigV2,
    code_gate_enabled_v2 as live_open_code_gate_enabled_v2,
    load_live_open_config_v2,
    save_live_open_config_v2,
)
from autotrader_open_sizing_v2 import EntrySizingError, preflight_minimum_entry_v2
from autotrader_pilot_equity_v2 import load_pilot_equity_v2
from autotrader_strategy_catalog_v2 import strategy_spec_v2
from autotrader_strategy_enrollment_v2 import (
    EXECUTION_MODE_LIVE,
    load_active_strategy_enrollments_v2,
    set_live_open_armed_v2,
)
from saxo_provider import LIVE_BASE_URL, SaxoInstrument, configured_client
from trading_desk_v2_context import TradingDeskV2Context


def _account_info(client, account_id: str) -> tuple[str, str]:
    payload = client._get("port/v1/accounts/me")
    rows = payload.get("Data") or []
    if not isinstance(rows, list):
        raise RuntimeError("Saxo account list had invalid format")
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("AccountId") or "") != str(account_id):
            continue
        if not bool(row.get("Active", True)):
            raise RuntimeError("Saxo account is not active")
        account_key = str(row.get("AccountKey") or "").strip()
        currency = str(row.get("Currency") or "").strip().upper()
        if not account_key or not currency:
            raise RuntimeError("Saxo account is missing AccountKey/Currency")
        return account_key, currency
    raise RuntimeError("could not resolve Saxo account")


def _required_entry_directions(strategy_key: str) -> tuple[str, ...]:
    spec = strategy_spec_v2(strategy_key)
    return ("LONG", "SHORT") if spec.can_short else ("LONG",)


def _pilot_label(enrollment) -> str:
    spec = strategy_spec_v2(enrollment.strategy_key)
    return f"{spec.label} · UIC {enrollment.uic} · {enrollment.asset_type}"


def _money(value: float | None, currency: str) -> str:
    if value is None:
        return "—"
    return f"{float(value):,.2f} {currency}".replace(",", " ")


def render_tradingdesk_autotrade_entry_gate_v2(context: TradingDeskV2Context) -> None:
    """Configure explicit entry admission and execution arming for active LIVE pilots."""
    st.markdown("**LIVE entry-gate**")
    st.caption("Produkt-admission · margin envelope · Saxo precheck · separat arming")

    enrollments = tuple(
        item
        for item in load_active_strategy_enrollments_v2()
        if item.execution_mode == EXECUTION_MODE_LIVE
        and item.enabled
        and int(item.market_id) == int(context.market_id)
    )
    if not enrollments:
        st.caption("Ingen aktiv LIVE AutoManage-pilot på dette markedet ennå.")
        return

    enrollment = st.selectbox(
        "LIVE-pilot",
        enrollments,
        format_func=_pilot_label,
        key=f"td-entry-pilot:{context.market_id}",
    )
    spec = strategy_spec_v2(enrollment.strategy_key)
    required_directions = _required_entry_directions(enrollment.strategy_key)

    client = configured_client()
    if client is None or client.base_url.rstrip("/").lower() != LIVE_BASE_URL.lower():
        st.warning("Saxo LIVE er ikke tilgjengelig; entry-gaten kan ikke preflightes eller armes.")
        return

    try:
        account_key, currency = _account_info(client, enrollment.account_id)
        equity = load_pilot_equity_v2(pilot_key=enrollment.pilot_key)
    except Exception as exc:
        st.warning(f"Kunne ikke lese pilot/account state: {exc}")
        return
    if equity.currency.upper() != currency.upper():
        st.error("Pilotvaluta og Saxo-kontovaluta er forskjellige. LIVE entry er blokkert.")
        return

    st.caption(
        f"{spec.label} · pilotkapital {_money(equity.equity, currency)} · "
        f"entry-retninger {', '.join(required_directions)}"
    )

    margin_product = is_margin_product_v2(enrollment.asset_type)
    if margin_product:
        risk_verified = st.checkbox(
            "Jeg har verifisert at denne Saxo-kontoen har negative balance protection for dette marginproduktet.",
            key=f"td-entry-nbp:{enrollment.pilot_key}",
            help="PriceGauger infererer aldri denne beskyttelsen fra produktnavn eller marginprosent.",
        )
    else:
        risk_verified = st.checkbox(
            "Jeg har verifisert limited-loss og at produktet ikke kan skape marginforpliktelse utover innsatsen.",
            key=f"td-entry-limited-loss:{enrollment.pilot_key}",
        )

    instrument = SaxoInstrument(
        asset=enrollment.market_name,
        uic=enrollment.uic,
        asset_type=enrollment.asset_type,
    )

    admissions = {}
    for direction in required_directions:
        admission = load_product_admission_v2(
            account_id=enrollment.account_id,
            uic=enrollment.uic,
            asset_type=enrollment.asset_type,
            direction=direction,
        )
        admissions[direction] = admission
        st.markdown(f"**{direction} entry**")
        if admission is not None and admission.enabled:
            st.caption(
                "Godkjent · min amount "
                f"{admission.preflight_amount:g} · margin {_money(admission.preflight_initial_margin_account, currency)} · "
                f"notional {_money(admission.preflight_notional_account, currency)} · "
                f"kost {_money(admission.preflight_cost_account, currency)}"
            )
            continue

        if st.button(
            f"Preflight og godkjenn {direction}",
            disabled=not risk_verified,
            key=f"td-entry-preflight:{enrollment.pilot_key}:{direction}",
            use_container_width=True,
        ):
            try:
                reference = str(
                    uuid5(
                        NAMESPACE_URL,
                        f"entry-preflight|{enrollment.pilot_key}|{direction}",
                    )
                )
                _, preflight = preflight_minimum_entry_v2(
                    client,
                    account_key=account_key,
                    account_currency=currency,
                    instrument=instrument,
                    direction=direction,
                    external_reference=f"pg-admit-{reference.replace('-', '')[:30]}",
                )
                save_product_admission_v2(
                    enrollment,
                    direction=direction,
                    transaction_costs_verified=True,
                    margin_product_allowed=margin_product,
                    negative_balance_protection_verified=bool(risk_verified) if margin_product else False,
                    limited_loss_verified=bool(risk_verified) if not margin_product else False,
                    no_margin_obligation_verified=bool(risk_verified) if not margin_product else False,
                    preflight_amount=preflight.amount,
                    preflight_cost_account=preflight.estimated_cost_account,
                    preflight_initial_margin_account=preflight.initial_margin_account,
                    preflight_notional_account=preflight.notional_account,
                    enabled=True,
                )
            except (EntrySizingError, ValueError, RuntimeError) as exc:
                st.error(f"{direction} kunne ikke godkjennes: {exc}")
                return
            st.success(f"{direction} er eksplisitt godkjent for denne account/product-identiteten.")
            st.rerun()

    saved_margin = load_pilot_margin_config_v2(enrollment.pilot_key)
    default_leverage = 5.0 if saved_margin is None else float(saved_margin.max_effective_leverage)
    default_buffer = 0.0 if saved_margin is None else float(saved_margin.minimum_free_capital)
    max_leverage = st.number_input(
        "Maks effektiv leverage",
        min_value=1.0,
        max_value=50.0,
        value=default_leverage,
        step=0.5,
        key=f"td-entry-max-leverage:{enrollment.pilot_key}",
        help="Hard grense: resulting notional / pilotens aktuelle settled capital.",
    )
    free_buffer = st.number_input(
        f"Minimum fri margin ({currency})",
        min_value=0.0,
        value=default_buffer,
        step=50.0,
        key=f"td-entry-free-buffer:{enrollment.pilot_key}",
        help="Saxo precheck må vise minst denne frie marginen etter ordren.",
    )

    minimum_required_leverage = 0.0
    for admission in admissions.values():
        if admission is None or admission.preflight_notional_account is None or equity.entry_budget <= 0:
            continue
        minimum_required_leverage = max(
            minimum_required_leverage,
            float(admission.preflight_notional_account) / float(equity.entry_budget),
        )
    if minimum_required_leverage > 0:
        st.caption(f"Minste preflight-ordre tilsvarer ca. {minimum_required_leverage:.2f}× av dagens pilotkapital.")
        if float(max_leverage) + 1e-9 < minimum_required_leverage:
            st.warning("Valgt leverage-grense er lavere enn minste lovlige Saxo-ordre; re-entry vil bli blokkert.")

    if st.button(
        "Lagre Margin Envelope",
        key=f"td-entry-save-envelope:{enrollment.pilot_key}",
        use_container_width=True,
    ):
        try:
            save_pilot_margin_config_v2(
                pilot_key=enrollment.pilot_key,
                max_effective_leverage=float(max_leverage),
                minimum_free_capital=float(free_buffer),
                enabled=True,
            )
        except Exception as exc:
            st.error(f"Margin Envelope kunne ikke lagres: {exc}")
            return
        st.success("Margin Envelope er lagret.")
        st.rerun()

    margin_config = load_pilot_margin_config_v2(enrollment.pilot_key)
    admissions_ready = all(
        (item := load_product_admission_v2(
            account_id=enrollment.account_id,
            uic=enrollment.uic,
            asset_type=enrollment.asset_type,
            direction=direction,
        )) is not None and item.enabled
        for direction in required_directions
    )
    margin_ready = bool(margin_config and margin_config.enabled)

    close_config = load_live_close_config_v1()
    open_config = load_live_open_config_v2()
    close_code = live_close_code_gate_enabled_v1()
    open_code = live_open_code_gate_enabled_v2()
    st.caption(
        "Execution gates · "
        f"CLOSE code={'ON' if close_code else 'OFF'} / master={'ON' if close_config.armed else 'OFF'} · "
        f"OPEN code={'ON' if open_code else 'OFF'} / master={'ON' if open_config.armed else 'OFF'} / "
        f"pilot={'ON' if enrollment.live_open_armed else 'OFF'}"
    )

    close_ack = st.checkbox(
        "Jeg godkjenner LIVE CLOSE for eksplisitt AutoManaged posisjon gjennom PriceGaugers safety gates.",
        key=f"td-close-master-ack:{enrollment.pilot_key}",
    )
    if not close_config.armed:
        if st.button(
            "Arm LIVE CLOSE master",
            disabled=not close_ack,
            key=f"td-close-master-arm:{enrollment.pilot_key}",
            use_container_width=True,
        ):
            save_live_close_config_v1(LiveCloseConfigV1(armed=True))
            st.success("LIVE CLOSE master er armed. Code-gaten må også være ON i deployment.")
            st.rerun()

    entry_ack = st.checkbox(
        "Jeg godkjenner at denne LIVE-piloten kan åpne/re-entere ekte Saxo-posisjoner innenfor Product Universe, Margin Envelope og precheck.",
        key=f"td-open-pilot-ack:{enrollment.pilot_key}",
    )
    can_arm_open = admissions_ready and margin_ready and bool(entry_ack)
    if not enrollment.live_open_armed:
        if st.button(
            "Arm LIVE entry/re-entry",
            type="primary",
            disabled=not can_arm_open,
            key=f"td-open-pilot-arm:{enrollment.pilot_key}",
            use_container_width=True,
        ):
            save_live_open_config_v2(LiveOpenConfigV2(armed=True))
            set_live_open_armed_v2(enrollment.pilot_key, True)
            st.success("LIVE entry/re-entry er armed for denne piloten. Alle runtime-gater revalideres før hver ordre.")
            st.rerun()
    else:
        st.success("LIVE entry/re-entry er armed for denne piloten.")
        if st.button(
            "Disarm LIVE entry/re-entry",
            key=f"td-open-pilot-disarm:{enrollment.pilot_key}",
            use_container_width=True,
        ):
            set_live_open_armed_v2(enrollment.pilot_key, False)
            st.warning("LIVE entry/re-entry er disarmed for denne piloten.")
            st.rerun()

    if not admissions_ready:
        st.caption("OPEN er fortsatt fail-closed: alle nødvendige retninger må være eksplisitt produktgodkjent.")
    elif not margin_ready:
        st.caption("OPEN er fortsatt fail-closed: Margin Envelope må lagres.")
    elif not open_code:
        st.caption("Pilot/master kan konfigureres nå, men deployment code-gaten må være ON før noen LIVE OPEN POST er mulig.")


__all__ = ["render_tradingdesk_autotrade_entry_gate_v2"]
