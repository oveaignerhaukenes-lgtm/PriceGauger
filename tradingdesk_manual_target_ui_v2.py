from __future__ import annotations

import streamlit as st

from autotrader_manual_target_v2 import (
    TARGET_PENDING,
    load_manual_target_quote_v2,
    load_manual_target_state_v2,
    request_manual_target_v2,
)
from autotrader_risk_control_v2 import _position_observations_v2
from autotrader_strategy_catalog_v2 import strategy_spec_v2
from autotrader_strategy_enrollment_v2 import EXECUTION_MODE_LIVE, load_active_strategy_enrollments_v2
from saxo_provider import LIVE_BASE_URL, configured_client
from trading_desk_v2_context import TradingDeskV2Context


def _account_key(client, account_id: str) -> str:
    payload = client._get("port/v1/accounts/me")
    rows = payload.get("Data") or []
    if not isinstance(rows, list):
        raise RuntimeError("Saxo account list had invalid format")
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("AccountId") or "") != str(account_id):
            continue
        key = str(row.get("AccountKey") or "").strip()
        if key:
            return key
    raise RuntimeError("could not resolve Saxo AccountKey")


def _observed_direction(enrollment, observations) -> str:
    matches = tuple(
        item
        for item in observations
        if item.account_id == enrollment.account_id
        and int(item.uic) == int(enrollment.uic)
        and item.asset_type == enrollment.asset_type
    )
    if not matches:
        return "FLAT"
    if len(matches) != 1:
        return "UKLAR"
    side = matches[0].direction.strip().lower()
    if side == "buy":
        return "LONG"
    if side == "sell":
        return "SHORT"
    return "UKLAR"


def render_tradingdesk_manual_target_v2(context: TradingDeskV2Context) -> None:
    """Render a simple user target above the detailed AutoManager execution controls."""
    try:
        enrollments = tuple(
            item
            for item in load_active_strategy_enrollments_v2()
            if item.execution_mode == EXECUTION_MODE_LIVE
            and item.enabled
            and int(item.market_id) == int(context.market_id)
        )
    except Exception:
        return
    if not enrollments:
        return

    enrollment = enrollments[0]
    if len(enrollments) > 1:
        enrollment = st.selectbox(
            "Posisjonsmål · LIVE-pilot",
            enrollments,
            format_func=lambda item: strategy_spec_v2(item.strategy_key).label,
            key=f"td-manual-target-pilot:{context.market_id}",
        )

    client = configured_client()
    if client is None or client.base_url.rstrip("/").lower() != LIVE_BASE_URL.lower():
        return

    try:
        observations = _position_observations_v2(client)
        observed = _observed_direction(enrollment, observations)
        account_key = _account_key(client, enrollment.account_id)
        quote = load_manual_target_quote_v2(enrollment, account_key=account_key)
    except Exception as exc:
        st.caption(f"Posisjonsknappene venter på Saxo-pris: {exc}")
        return

    spec = strategy_spec_v2(enrollment.strategy_key)
    st.markdown("**Sett posisjon · AutoManager overtar**")
    st.caption(
        f"Nå: {observed} · {spec.label}. Klikk LONG eller SHORT som ønsket mål; "
        "PriceGauger bruker samme sizing, margin og CLOSE → FLAT → OPEN-livssyklus som strategiene."
    )

    state = load_manual_target_state_v2(enrollment.pilot_key)
    if state is not None and state.status == TARGET_PENDING:
        st.info(f"Brukermål pågår: {state.target_direction}. Strategisignaler venter til målet er observert hos Saxo.")

    long_col, short_col = st.columns(2)
    long_clicked = long_col.button(
        f"LONG · KJØP @ {quote.ask:,.2f}".replace(",", " "),
        type="primary" if observed != "LONG" else "secondary",
        disabled=observed in {"LONG", "UKLAR"},
        key=f"td-manual-target-long:{enrollment.pilot_key}",
        use_container_width=True,
        help="Viser aktuell ASK. Klikket sender ikke ordre fra nettleseren; det oppretter et AutoManager-mål.",
    )
    short_clicked = short_col.button(
        f"SHORT · SELG @ {quote.bid:,.2f}".replace(",", " "),
        type="primary" if observed != "SHORT" else "secondary",
        disabled=observed in {"SHORT", "UKLAR"},
        key=f"td-manual-target-short:{enrollment.pilot_key}",
        use_container_width=True,
        help="Viser aktuell BID. Klikket sender ikke ordre fra nettleseren; det oppretter et AutoManager-mål.",
    )

    target = "LONG" if long_clicked else ("SHORT" if short_clicked else None)
    if target is None:
        return
    try:
        result = request_manual_target_v2(enrollment, target_direction=target)
    except Exception as exc:
        st.error(f"{target}-målet kunne ikke settes: {exc}")
        return
    if result.already_observed:
        st.success(f"Saxo er allerede {target}; strategien starter på nytt fra denne observerte posisjonen.")
    elif result.request_created:
        action = "OPEN" if result.observed_direction == "FLAT" else "CLOSE → FLAT → OPEN"
        st.success(f"Mål satt til {target}. Starter {action}; AutoManager fortsetter derfra.")
    else:
        st.success(f"Mål satt til {target}; execution-motoren fortsetter på neste syklus.")
    st.rerun()


__all__ = ["render_tradingdesk_manual_target_v2"]
