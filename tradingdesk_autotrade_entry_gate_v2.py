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
from autotrader_entry_sizing_policy_v2 import (
    SIZING_MODE_FIXED,
    SIZING_MODE_MAX,
    load_entry_sizing_policy_v2,
    save_entry_sizing_policy_v2,
)
from autotrader_live_close_v1 import (
    LiveCloseConfigV1,
    code_gate_enabled_v1 as live_close_code_gate_enabled_v1,
    load_live_close_config_v1,
    save_live_close_config_v1,
)
from autotrader_live_open_v2 import (
    LiveOpenConfigV2,
    approve_open_request_v2,
    code_gate_enabled_v2 as live_open_code_gate_enabled_v2,
    load_live_open_config_v2,
    load_open_requests_waiting_approval_v2,
    save_live_open_config_v2,
)
from autotrader_open_sizing_v2 import (
    EntrySizingError,
    find_largest_legal_entry_v2,
    preflight_minimum_entry_v2,
)
from autotrader_pilot_equity_v2 import load_pilot_equity_v2
from autotrader_strategy_catalog_v2 import AUTOTRADER_STRATEGIES_V2, strategy_spec_v2
from autotrader_strategy_enrollment_v2 import (
    ENTRY_MODE_APPROVAL_REQUIRED,
    ENTRY_MODE_AUTO,
    ENTRY_MODE_MANUAL_ONLY,
    EXECUTION_MODE_LIVE,
    load_active_strategy_enrollments_v2,
    set_entry_mode_v2,
    set_live_open_armed_v2,
)
from autotrader_strategy_switch_v2 import switch_live_strategy_v2
from saxo_provider import LIVE_BASE_URL, SaxoInstrument, configured_client
from trading_desk_v2_context import TradingDeskV2Context


ENTRY_MODE_LABELS = {
    ENTRY_MODE_MANUAL_ONLY: "Manage-only · automatisk exit, ingen re-entry",
    ENTRY_MODE_AUTO: "Full auto · automatisk exit + re-entry",
    ENTRY_MODE_APPROVAL_REQUIRED: "Godkjenn re-entry · automatisk exit",
}

SIZING_MODE_LABELS = {
    SIZING_MODE_MAX: "Maks innen pilotrammen · all-in",
    SIZING_MODE_FIXED: "Fast amount · incremental",
}


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
    directions: list[str] = []
    if spec.can_long:
        directions.append("LONG")
    if spec.can_short:
        directions.append("SHORT")
    return tuple(directions)


def _pilot_label(enrollment) -> str:
    spec = strategy_spec_v2(enrollment.strategy_key)
    return f"{spec.label} · UIC {enrollment.uic} · {enrollment.asset_type}"


def _money(value: float | None, currency: str) -> str:
    if value is None:
        return "—"
    return f"{float(value):,.2f} {currency}".replace(",", " ")


def _execution_flow_text(spec, entry_mode: str) -> str:
    if spec.key == "macd-mtf-30-10-5-long-flat-v1":
        if entry_mode == ENTRY_MODE_AUTO:
            return (
                "MTF long/flat · Full auto: 30m gir context/regime; lukket 5m CROSS_UP åpner LONG; "
                "10m validerer eller avkrefter det tidlige forsøket; 30m bekrefter hovedregimet eller avslutter LONG "
                "på bearish kryss. Alle OPEN/CLOSE går gjennom de samme LIVE safety-gatene."
            )
        if entry_mode == ENTRY_MODE_APPROVAL_REQUIRED:
            return (
                "MTF long/flat · Godkjenn re-entry: 5m kan lage en tidlig LONG-request i gyldig 30m-context, "
                "men OPEN krever one-shot godkjenning. 10m og 30m kan senere validere eller lukke automatisk."
            )
        return (
            "MTF long/flat · Manage-only: 10m/30m kan lukke en eksisterende LONG etter MTF-policyen, "
            "men 5m-entry åpner aldri ny LONG automatisk."
        )
    if spec.can_long and not spec.can_short:
        if entry_mode == ENTRY_MODE_AUTO:
            return (
                "Long/flat · Full auto: LONG → EXIT til FLAT på bearish 30m MACD-kryss → "
                "RE-ENTRY LONG på neste bullish kryss. Både exit og re-entry går gjennom LIVE safety-gatene."
            )
        if entry_mode == ENTRY_MODE_APPROVAL_REQUIRED:
            return (
                "Long/flat · Godkjenn re-entry: LONG → EXIT til FLAT automatisk på bearish kryss. "
                "Neste bullish kryss lager LONG re-entry-request som må godkjennes én gang."
            )
        return (
            "Long/flat · Manage-only: LONG → EXIT til FLAT automatisk på bearish kryss. "
            "PriceGauger stopper der og åpner ikke LONG igjen; du må gjøre re-entry manuelt."
        )
    if spec.can_short and not spec.can_long:
        if entry_mode == ENTRY_MODE_AUTO:
            return (
                "Short/flat · Full auto: SHORT → EXIT til FLAT på bullish 30m MACD-kryss → "
                "RE-ENTRY SHORT på neste bearish kryss."
            )
        if entry_mode == ENTRY_MODE_APPROVAL_REQUIRED:
            return (
                "Short/flat · Godkjenn re-entry: SHORT → FLAT automatisk; ny SHORT etter bearish kryss krever godkjenning."
            )
        return "Short/flat · Manage-only: SHORT → FLAT automatisk; ingen automatisk SHORT re-entry."
    if entry_mode == ENTRY_MODE_AUTO:
        return "MACD Switch · Full auto: bullish kryss → LONG; bearish kryss → SHORT, med CLOSE → bekreftet FLAT → OPEN."
    if entry_mode == ENTRY_MODE_APPROVAL_REQUIRED:
        return "MACD Switch · exit er automatisk, men hver ny LONG/SHORT OPEN etter switch krever one-shot godkjenning."
    return "MACD Switch · Manage-only kan lukke den eksisterende siden, men åpner aldri motsatt side automatisk."


def _render_strategy_switch(enrollment) -> None:
    strategies = tuple(AUTOTRADER_STRATEGIES_V2)
    if not strategies:
        return
    current_index = next(
        (index for index, item in enumerate(strategies) if item.key == enrollment.strategy_key),
        0,
    )
    target = st.selectbox(
        "LIVE-strategi",
        strategies,
        index=current_index,
        format_func=lambda item: item.label,
        key=f"td-live-strategy-switch-target:{enrollment.pilot_key}",
        help="Velg strategi. Byttet beholder eventuell åpen Saxo-posisjon.",
    )
    st.caption(
        "Bytt LIVE-strategi direkte i listen. Selve byttet sender ingen ordre; eksisterende eksponering blir stående."
    )
    st.caption(target.description)
    if target.key == enrollment.strategy_key:
        return
    try:
        result = switch_live_strategy_v2(
            pilot_key=enrollment.pilot_key,
            target_strategy_key=target.key,
        )
    except Exception as exc:
        st.error(f"Strategien kunne ikke byttes: {exc}")
        return
    st.success(
        f"LIVE-strategi er byttet til {target.label}. Eksponering ved byttet var {result.observed_direction}."
    )
    st.rerun()


def _render_armed_badge(enrollment) -> None:
    close_config = load_live_close_config_v1()
    open_config = load_live_open_config_v2()
    close_active = bool(live_close_code_gate_enabled_v1() and close_config.armed)
    open_active = bool(
        live_open_code_gate_enabled_v2()
        and open_config.armed
        and enrollment.live_open_armed
        and enrollment.entry_mode != ENTRY_MODE_MANUAL_ONLY
    )
    if not close_active and not open_active:
        return
    if close_active and open_active:
        label = "LIVE ARMED"
        detail = "CLOSE + OPEN/re-entry authority er aktiv for valgt LIVE-pilot"
    elif open_active:
        label = "OPEN ARMED"
        detail = "OPEN/re-entry authority er aktiv; CLOSE er ikke aktiv"
    else:
        label = "CLOSE ARMED"
        detail = "CLOSE authority er aktiv; OPEN/re-entry er ikke aktiv"
    st.markdown(
        f"""
        <div title="{detail}" style="
            position: fixed;
            right: 1.15rem;
            bottom: 1.05rem;
            z-index: 9999;
            padding: 0.42rem 0.68rem;
            border-radius: 999px;
            border: 1px solid rgba(255, 75, 75, 0.72);
            background: rgba(48, 15, 18, 0.94);
            color: #ff7676;
            font-size: 0.78rem;
            font-weight: 700;
            letter-spacing: 0.03em;
            box-shadow: 0 2px 12px rgba(0,0,0,0.28);
        "><span style="font-size:0.9rem;">●</span>&nbsp; {label}</div>
        """,
        unsafe_allow_html=True,
    )


def _render_close_gate(enrollment) -> None:
    close_config = load_live_close_config_v1()
    if enrollment.entry_mode == ENTRY_MODE_AUTO and not close_config.armed:
        close_config = save_live_close_config_v1(LiveCloseConfigV1(armed=True))
    close_code = live_close_code_enabled = live_close_code_gate_enabled_v1()
    st.caption(
        f"CLOSE gate · code={'ON' if close_code else 'OFF'} · master={'ON' if close_config.armed else 'OFF'}"
    )
    if close_config.armed:
        if live_close_code_enabled:
            st.success("LIVE CLOSE er ARMED. Strategiens exits krever ingen ny manuell godkjenning.")
        else:
            st.warning("LIVE CLOSE master er armed, men deployment code-gaten er OFF.")
        return
    close_ack = st.checkbox(
        "Jeg godkjenner automatisk LIVE CLOSE for eksplisitt AutoManaged posisjon gjennom PriceGaugers safety gates.",
        key=f"td-close-master-ack:{enrollment.pilot_key}",
    )
    if st.button(
        "Arm automatisk LIVE CLOSE",
        disabled=not close_ack,
        key=f"td-close-master-arm:{enrollment.pilot_key}",
        use_container_width=True,
    ):
        save_live_close_config_v1(LiveCloseConfigV1(armed=True))
        st.success("LIVE CLOSE master er armed. Code-gaten må også være ON i deployment.")
        st.rerun()


def _render_pending_approvals(enrollment, currency: str) -> None:
    requests = load_open_requests_waiting_approval_v2(enrollment.pilot_key)
    if not requests:
        st.caption("Ingen fersk entry venter på godkjenning.")
        return
    st.markdown("**Venter på godkjenning**")
    for request in requests:
        signal_at = str(request.get("signal_at") or "")
        direction = str(request.get("desired_direction") or "?")
        signal = str(request.get("signal") or "?")
        budget = float(request.get("budget_amount") or 0.0)
        request_id = str(request["request_id"])
        st.caption(
            f"{direction} · {signal} · {signal_at} · signalbudsjett {_money(budget, currency)}"
        )
        if st.button(
            f"Godkjenn denne {direction}-entryen",
            type="primary",
            key=f"td-approve-open:{request_id}",
            use_container_width=True,
        ):
            try:
                approve_open_request_v2(
                    pilot_key=enrollment.pilot_key,
                    request_id=request_id,
                    source="TRADINGDESK",
                )
            except Exception as exc:
                st.error(f"Entry kunne ikke godkjennes: {exc}")
                return
            st.success("Kun denne execution-requesten er godkjent. Runtime revaliderer alle gates før POST.")
            st.rerun()


def _render_sizing_controls(
    *,
    enrollment,
    account_key: str,
    currency: str,
    admissions: dict[str, object],
) -> bool:
    """Return True when the visible sizing controls match persisted execution policy."""
    st.markdown("**Ordrestørrelse ved OPEN/re-entry**")
    st.caption(
        "Maks innen pilotrammen bruker størst Saxo-godkjente amount som Margin Envelope tillater. "
        "Fast amount sender alltid samme amount eller blokkerer; den skaleres aldri lydløst."
    )
    clean = True
    for direction, admission in admissions.items():
        policy = load_entry_sizing_policy_v2(
            account_key=account_key,
            uic=enrollment.uic,
            asset_type=enrollment.asset_type,
            direction=direction,
        )
        key_base = f"td-entry-sizing:{enrollment.pilot_key}:{direction}"
        selected = st.selectbox(
            f"{direction} sizing",
            (SIZING_MODE_MAX, SIZING_MODE_FIXED),
            index=0 if policy.sizing_mode == SIZING_MODE_MAX else 1,
            format_func=lambda item: SIZING_MODE_LABELS[item],
            key=f"{key_base}:mode",
            help=(
                "All-in betyr kun innen den isolerte pilotkapitalen og Margin Envelope, aldri resten av Saxo-kontoen."
            ),
        )
        minimum = None if admission is None else getattr(admission, "preflight_amount", None)
        default_fixed = float(policy.fixed_amount or minimum or 1.0)
        fixed_amount = None
        if selected == SIZING_MODE_FIXED:
            fixed_amount = st.number_input(
                f"{direction} amount per entry",
                min_value=float(minimum or 0.00000001),
                value=max(default_fixed, float(minimum or 0.00000001)),
                step=float(minimum or 0.01),
                format="%.8f",
                key=f"{key_base}:fixed",
                help="Prefylt med Saxo-discovered minimum. Runtime krever eksakt lovlig amount og gjør ny precheck før ordre.",
            )
            if minimum is not None:
                st.caption(f"Saxo-discovered minimum for {direction}: {float(minimum):g}")

        dirty = selected != policy.sizing_mode
        if selected == SIZING_MODE_FIXED:
            dirty = dirty or policy.fixed_amount is None or abs(float(fixed_amount) - float(policy.fixed_amount)) > 1e-12
        if dirty:
            clean = False
            st.caption("Endringen er ikke aktiv før den lagres.")
        persisted_text = (
            "Maks innen pilotrammen"
            if policy.sizing_mode == SIZING_MODE_MAX
            else f"Fast amount {float(policy.fixed_amount or 0.0):g}"
        )
        st.caption(f"Aktiv execution-policy: {persisted_text}")
        if st.button(
            f"Lagre {direction} ordrestørrelse",
            key=f"{key_base}:save",
            use_container_width=True,
        ):
            try:
                save_entry_sizing_policy_v2(
                    account_key=account_key,
                    uic=enrollment.uic,
                    asset_type=enrollment.asset_type,
                    direction=direction,
                    sizing_mode=selected,
                    fixed_amount=None if selected == SIZING_MODE_MAX else float(fixed_amount),
                )
            except Exception as exc:
                st.error(f"Ordrestørrelsen kunne ikke lagres: {exc}")
                return False
            st.success(f"{direction} sizing er lagret.")
            st.rerun()
    return clean


def render_tradingdesk_autotrade_entry_gate_v2(context: TradingDeskV2Context) -> None:
    """Configure how an active AutoManage pilot is allowed to create new exposure."""
    st.markdown("**AutoManage execution**")
    st.caption("Velg strategi og entry-modus. Full auto betyr automatisk exit + re-entry uten ekstra pilot-arming.")

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
    _render_strategy_switch(enrollment)

    client = configured_client()
    if client is None or client.base_url.rstrip("/").lower() != LIVE_BASE_URL.lower():
        st.warning("Saxo LIVE er ikke tilgjengelig; execution-gaten kan ikke konfigureres.")
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
        f"entry-mode {ENTRY_MODE_LABELS.get(enrollment.entry_mode, enrollment.entry_mode)}"
    )

    mode_options = (
        ENTRY_MODE_MANUAL_ONLY,
        ENTRY_MODE_AUTO,
        ENTRY_MODE_APPROVAL_REQUIRED,
    )
    selected_mode = st.selectbox(
        "Entry-adferd",
        mode_options,
        index=mode_options.index(enrollment.entry_mode) if enrollment.entry_mode in mode_options else 0,
        format_func=lambda item: ENTRY_MODE_LABELS[item],
        key=f"td-entry-mode:{enrollment.pilot_key}",
        help=(
            "Manage-only: automatisk exit er mulig, men PG gjør aldri re-entry. "
            "Full auto: exit og senere re-entry skjer automatisk når strategien signaliserer det. "
            "Godkjenn re-entry: exit er automatisk, men hver ny OPEN må godkjennes one-shot."
        ),
    )
    st.info(_execution_flow_text(spec, selected_mode))
    if selected_mode != enrollment.entry_mode:
        if st.button(
            "Lagre entry-adferd",
            key=f"td-entry-mode-save:{enrollment.pilot_key}",
            use_container_width=True,
        ):
            set_entry_mode_v2(enrollment.pilot_key, selected_mode)
            if selected_mode == ENTRY_MODE_AUTO:
                save_live_open_config_v2(LiveOpenConfigV2(armed=True))
                save_live_close_config_v1(LiveCloseConfigV1(armed=True))
            st.success("Entry-adferd er endret.")
            st.rerun()

    _render_close_gate(enrollment)
    _render_armed_badge(enrollment)

    if enrollment.entry_mode == ENTRY_MODE_MANUAL_ONLY:
        st.info(
            "Manage-only: PriceGauger kan håndtere exit fra posisjonen, men sender aldri OPEN/re-entry. "
            "Etter exit forblir piloten FLAT til du selv åpner en ny posisjon. Ingen Product Admission eller Margin Envelope kreves."
        )
        return

    required_directions = _required_entry_directions(enrollment.strategy_key)
    st.caption(f"Automatisk/approvable re-entry krever Product Admission for: {', '.join(required_directions)}")

    margin_product = is_margin_product_v2(enrollment.asset_type)
    admissions = {
        direction: load_product_admission_v2(
            account_id=enrollment.account_id,
            uic=enrollment.uic,
            asset_type=enrollment.asset_type,
            direction=direction,
        )
        for direction in required_directions
    }
    all_safety_verified = bool(admissions) and all(
        admission is not None
        and (
            admission.negative_balance_protection_verified
            if margin_product
            else (admission.limited_loss_verified and admission.no_margin_obligation_verified)
        )
        for admission in admissions.values()
    )
    if all_safety_verified:
        risk_verified = True
        st.caption(
            "Kontobeskyttelsen for dette eksakte Saxo-produktet er allerede verifisert og lagret i Product Admission."
        )
    elif margin_product:
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

    for direction in required_directions:
        admission = admissions[direction]
        st.markdown(f"**{direction} re-entry**")

        already_verified = bool(
            admission
            and (
                admission.negative_balance_protection_verified
                if margin_product
                else (admission.limited_loss_verified and admission.no_margin_obligation_verified)
            )
        )
        safety_ack = bool(risk_verified or already_verified)
        run_preflight = False

        if admission is not None and admission.enabled:
            st.caption(
                "Godkjent · min amount "
                f"{admission.preflight_amount:g} · margin {_money(admission.preflight_initial_margin_account, currency)} · "
                f"notional {_money(admission.preflight_notional_account, currency)} · "
                f"kost {_money(admission.preflight_cost_account, currency)}"
            )
            st.caption(
                "Størrelsesdata kan revalideres uten ordre dersom Saxo-regler eller PriceGauger sizing-kontrakt er endret."
            )
            run_preflight = st.button(
                f"Revalider Saxo-størrelse for {direction}",
                disabled=not safety_ack,
                key=f"td-entry-revalidate:{enrollment.pilot_key}:{direction}",
                use_container_width=True,
            )
        else:
            run_preflight = st.button(
                f"Preflight og godkjenn {direction}",
                disabled=not safety_ack,
                key=f"td-entry-preflight:{enrollment.pilot_key}:{direction}",
                use_container_width=True,
            )

        if run_preflight:
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
                    negative_balance_protection_verified=bool(safety_ack) if margin_product else False,
                    limited_loss_verified=bool(safety_ack) if not margin_product else False,
                    no_margin_obligation_verified=bool(safety_ack) if not margin_product else False,
                    preflight_amount=preflight.amount,
                    preflight_cost_account=preflight.estimated_cost_account,
                    preflight_initial_margin_account=preflight.initial_margin_account,
                    preflight_notional_account=preflight.notional_account,
                    enabled=True,
                )
            except (EntrySizingError, ValueError, RuntimeError) as exc:
                st.error(f"{direction} kunne ikke godkjennes: {exc}")
                return
            st.success(
                f"{direction} er revalidert mot Saxo: min amount {preflight.amount:g}, "
                f"margin {_money(preflight.initial_margin_account, currency)}."
            )
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

    sizing_clean = _render_sizing_controls(
        enrollment=enrollment,
        account_key=account_key,
        currency=currency,
        admissions=admissions,
    )

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

    preview_key = f"td-entry-size-preview:{enrollment.pilot_key}"
    if admissions_ready and margin_ready and sizing_clean and equity.entry_budget > 0:
        if st.button(
            "Beregn ordrestørrelse nå · ingen ordre",
            key=f"{preview_key}:button",
            use_container_width=True,
            help="Kjører Saxo precheck og Margin Envelope, men sender ingen ordre.",
        ):
            preview_rows = []
            try:
                envelope = margin_config.envelope(currency=currency, controlled_capital=float(equity.entry_budget))
                for direction in required_directions:
                    ref = uuid5(
                        NAMESPACE_URL,
                        f"entry-preview|{enrollment.pilot_key}|{direction}|{equity.entry_budget}",
                    )
                    sizing = find_largest_legal_entry_v2(
                        client,
                        account_key=account_key,
                        account_currency=currency,
                        instrument=instrument,
                        direction=direction,
                        envelope=envelope,
                        controlled_capital=float(equity.entry_budget),
                        external_reference_prefix=f"pg-preview-{str(ref).replace('-', '')[:22]}",
                    )
                    final = sizing.final_precheck
                    preview_rows.append(
                        {
                            "direction": direction,
                            "amount": float(sizing.amount),
                            "margin": float(final.initial_margin_account),
                            "notional": float(final.notional_account),
                            "free_after": float(final.available_margin_after_account),
                        }
                    )
                st.session_state[preview_key] = preview_rows
            except Exception as exc:
                st.session_state.pop(preview_key, None)
                st.error(f"Ordrestørrelsen kunne ikke preflightes: {exc}")
        for row in st.session_state.get(preview_key, []):
            st.success(
                f"Akkurat nå · {row['direction']}: amount {row['amount']:g} · "
                f"margin {_money(row['margin'], currency)} · notional {_money(row['notional'], currency)} · "
                f"fri margin etter {_money(row['free_after'], currency)}"
            )
        st.caption(
            "Maks-modus kan endre amount ved neste signal fordi Saxo-margin/pris revalideres. "
            "Fast amount endres aldri automatisk; hvis den ikke lenger er lovlig, blokkeres OPEN."
        )

    open_config = load_live_open_config_v2()
    if enrollment.entry_mode == ENTRY_MODE_AUTO and not open_config.armed:
        open_config = save_live_open_config_v2(LiveOpenConfigV2(armed=True))
    open_code = live_open_code_gate_enabled_v2()
    st.caption(
        "OPEN / re-entry gate · "
        f"code={'ON' if open_code else 'OFF'} · master={'ON' if open_config.armed else 'OFF'} · "
        f"pilot={'ON' if enrollment.live_open_armed else 'OFF'}"
    )

    if enrollment.entry_mode == ENTRY_MODE_AUTO:
        if enrollment.live_open_armed and open_config.armed and open_code:
            st.success("● Full auto er aktiv: neste gyldige OPEN/re-entry kan handles automatisk.")
        elif not open_code:
            st.warning("Full auto er valgt, men deployment code-gaten for LIVE OPEN er OFF.")
    else:
        if enrollment.live_open_armed and open_config.armed and open_code:
            st.success("● LIVE OPEN/re-entry er ARMED for denne piloten.")
        elif enrollment.live_open_armed:
            st.warning("Piloten er markert armed, men global master eller deployment code-gate er OFF.")

        if not enrollment.live_open_armed:
            entry_ack = st.checkbox(
                "Jeg godkjenner at denne LIVE-piloten kan sende en OPEN/re-entry når jeg eksplisitt godkjenner den konkrete requesten.",
                key=f"td-open-pilot-ack:{enrollment.pilot_key}",
            )
            can_arm_open = admissions_ready and margin_ready and sizing_clean and bool(entry_ack)
            if st.button(
                "Arm LIVE re-entry",
                type="primary",
                disabled=not can_arm_open,
                key=f"td-open-pilot-arm:{enrollment.pilot_key}",
                use_container_width=True,
            ):
                save_live_open_config_v2(LiveOpenConfigV2(armed=True))
                set_live_open_armed_v2(enrollment.pilot_key, True)
                st.success("LIVE OPEN/re-entry er armed. Alle runtime-gater revalideres før hver ordre.")
                st.rerun()
        else:
            st.success("Re-entry execution er armed, men hver OPEN krever one-shot godkjenning.")
            if st.button(
                "Disarm LIVE re-entry",
                key=f"td-open-pilot-disarm:{enrollment.pilot_key}",
                use_container_width=True,
            ):
                set_live_open_armed_v2(enrollment.pilot_key, False)
                st.warning("LIVE re-entry er disarmed for denne piloten. Automatisk CLOSE/exit påvirkes ikke.")
                st.rerun()

    if enrollment.entry_mode == ENTRY_MODE_APPROVAL_REQUIRED and enrollment.live_open_armed:
        _render_pending_approvals(enrollment, currency)

    if not admissions_ready:
        st.caption("OPEN er fail-closed: alle retninger strategien kan åpne må være eksplisitt produktgodkjent.")
    elif not margin_ready:
        st.caption("OPEN er fail-closed: Margin Envelope må lagres.")
    elif not sizing_clean:
        st.caption("OPEN er fail-closed: synlig sizing-valg må lagres før LIVE re-entry kan brukes.")
    elif not open_code:
        st.caption("Entry-modus er konfigurert, men deployment code-gaten må være ON før noen LIVE OPEN POST er mulig.")


__all__ = ["ENTRY_MODE_LABELS", "SIZING_MODE_LABELS", "render_tradingdesk_autotrade_entry_gate_v2"]