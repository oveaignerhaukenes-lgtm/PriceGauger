from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import streamlit as st

from autotrader_macd_flip_policy_v2 import MACD_FLIP_STRATEGY_V2
from autotrader_pilot_equity_v2 import DEFAULT_PILOT_SEED_CAPITAL, load_pilot_equity_v2
from autotrader_risk_control_v2 import PositionObservationV2, _position_observations_v2
from autotrader_strategy_enrollment_v2 import (
    StrategyEnrollmentV2,
    enroll_macd_flip_position_v2,
    load_strategy_enrollment_v2,
    stop_strategy_enrollment_v2,
)
from database import connect, using_postgres
from saxo_provider import LIVE_BASE_URL, configured_client
from trading_desk_v2_context import TradingDeskV2Context
from autotrader_live_pilot_runtime_v2 import resolve_live_pilot_binding_v2


STRATEGY_LABEL = "30m MACD flip"


@dataclass(frozen=True, slots=True)
class AutoManagePanelSnapshotV2:
    observation: PositionObservationV2
    enrollment: StrategyEnrollmentV2 | None
    pilot_key: str
    currency: str
    equity: float | None
    realized_net_pnl: float | None
    realized_events: int
    last_action: str | None
    last_outcome: str | None
    last_signal: str | None
    last_signal_at: str | None


def _account_currency(client, account_id: str) -> str | None:
    payload = client._get("port/v1/accounts/me")
    rows = payload.get("Data") or []
    if not isinstance(rows, list):
        return None
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("AccountId") or "") != str(account_id):
            continue
        currency = str(row.get("Currency") or "").strip().upper()
        return currency or None
    return None


def _candidate_positions_for_context(
    context: TradingDeskV2Context,
    observations: tuple[PositionObservationV2, ...],
) -> tuple[tuple[PositionObservationV2, str], ...]:
    matches: list[tuple[PositionObservationV2, str]] = []
    for observation in observations:
        try:
            binding = resolve_live_pilot_binding_v2(
                account_id=observation.account_id,
                anchor_net_position_id=observation.net_position_id,
                uic=observation.uic,
                asset_type=observation.asset_type,
            )
        except Exception:
            continue
        if int(binding.market_id) == int(context.market_id):
            matches.append((observation, binding.pilot_key))
    return tuple(matches)


def _latest_pilot_stats(pilot_key: str) -> tuple[int, str | None, str | None, str | None, str | None]:
    with connect() as db:
        count_row = db.execute(
            "SELECT COUNT(*) AS n FROM pg_v2_autotrader_pilot_equity_events WHERE pilot_key = ?",
            (pilot_key,),
        ).fetchone()
        latest = db.execute(
            """
            SELECT requested_action, outcome_reason, signal, signal_at
            FROM pg_v2_autotrader_live_pilot_evaluations
            WHERE pilot_key = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (pilot_key,),
        ).fetchone()
    if count_row is None:
        count = 0
    elif isinstance(count_row, dict):
        count = int(count_row.get("n") or 0)
    else:
        count = int(count_row[0] or 0)
    if latest is None:
        return count, None, None, None, None
    values = dict(latest) if isinstance(latest, dict) else {
        "requested_action": latest[0],
        "outcome_reason": latest[1],
        "signal": latest[2],
        "signal_at": latest[3],
    }
    return (
        count,
        None if values.get("requested_action") is None else str(values["requested_action"]),
        None if values.get("outcome_reason") is None else str(values["outcome_reason"]),
        None if values.get("signal") is None else str(values["signal"]),
        None if values.get("signal_at") is None else str(values["signal_at"]),
    )


def _snapshot(
    observation: PositionObservationV2,
    *,
    pilot_key: str,
    currency: str,
) -> AutoManagePanelSnapshotV2:
    enrollment = load_strategy_enrollment_v2(pilot_key)
    equity = None
    realized = None
    realized_events = 0
    last_action = None
    last_outcome = None
    last_signal = None
    last_signal_at = None
    if enrollment is not None:
        try:
            ledger = load_pilot_equity_v2(pilot_key=pilot_key)
            equity = ledger.equity
            realized = ledger.realized_net_pnl
        except Exception:
            pass
        try:
            (
                realized_events,
                last_action,
                last_outcome,
                last_signal,
                last_signal_at,
            ) = _latest_pilot_stats(pilot_key)
        except Exception:
            pass
    return AutoManagePanelSnapshotV2(
        observation=observation,
        enrollment=enrollment,
        pilot_key=pilot_key,
        currency=currency,
        equity=equity,
        realized_net_pnl=realized,
        realized_events=realized_events,
        last_action=last_action,
        last_outcome=last_outcome,
        last_signal=last_signal,
        last_signal_at=last_signal_at,
    )


def _position_label(item: tuple[PositionObservationV2, str]) -> str:
    observation, _ = item
    side = "LONG" if observation.direction.strip().lower() == "buy" else "SHORT"
    return f"{side} · {observation.asset_type} · UIC {observation.uic} · {observation.pnl_pct:+.2f}%"


def _metric_money(value: float | None, currency: str) -> str:
    if value is None:
        return "—"
    return f"{value:,.2f} {currency}".replace(",", " ")


def render_tradingdesk_automanage_panel_v2(context: TradingDeskV2Context) -> None:
    """Compact right-side context for explicitly enrolling one LIVE position."""
    st.markdown("**AutoManage**")
    st.caption("Eksakt LIVE-posisjon · 30m MACD flip · separat entry-gate")

    if not using_postgres():
        st.info("AutoManage krever PostgreSQL-runtime.")
        return

    client = configured_client()
    environment_ok = bool(client and client.base_url.rstrip("/").lower() == LIVE_BASE_URL.lower())
    if client is None or not environment_ok:
        st.info("Saxo LIVE er ikke tilgjengelig i web-runtime.")
        return

    try:
        observations = _position_observations_v2(client)
        candidates = _candidate_positions_for_context(context, observations)
    except Exception as exc:
        st.warning(f"Kunne ikke lese LIVE-posisjonene: {exc}")
        return

    if not candidates:
        st.caption("Ingen åpen LIVE-posisjon matcher dette canonical markedet.")
        return

    selected = st.selectbox(
        "Åpen posisjon",
        candidates,
        format_func=_position_label,
        key=f"td-automanage-position:{context.market_id}",
    )
    observation, pilot_key = selected
    currency = _account_currency(client, observation.account_id) or "NOK"
    snapshot = _snapshot(observation, pilot_key=pilot_key, currency=currency)

    side = "LONG" if observation.direction.strip().lower() == "buy" else "SHORT"
    c1, c2 = st.columns(2)
    c1.metric("Posisjon", side)
    c2.metric("P/L", f"{observation.pnl_pct:+.2f}%")
    c3, c4 = st.columns(2)
    c3.metric("Åpnet", f"{observation.average_open_price:g}")
    c4.metric("Nå", f"{observation.current_price:g}")
    st.caption(f"Amount {observation.amount:g} · UIC {observation.uic} · {observation.asset_type}")

    strategy = st.selectbox(
        "Strategi",
        (MACD_FLIP_STRATEGY_V2,),
        format_func=lambda _: STRATEGY_LABEL,
        key=f"td-automanage-strategy:{pilot_key}",
    )
    assert strategy == MACD_FLIP_STRATEGY_V2

    active = bool(snapshot.enrollment and snapshot.enrollment.enabled)
    if active:
        e1, e2 = st.columns(2)
        e1.metric("Pilotkapital", _metric_money(snapshot.equity, currency))
        e2.metric("Realisert", _metric_money(snapshot.realized_net_pnl, currency))
        status_bits = ["AUTO-MANAGED", f"trades {snapshot.realized_events}"]
        if snapshot.last_action:
            status_bits.append(f"siste {snapshot.last_action}")
        if snapshot.last_signal:
            status_bits.append(f"signal {snapshot.last_signal}")
        st.caption(" · ".join(status_bits))
        if snapshot.last_outcome:
            st.caption(f"Runtime: {snapshot.last_outcome}")

        st.toggle(
            "AutoTrade · flip/re-entry",
            value=bool(snapshot.enrollment.live_open_armed),
            disabled=True,
            help=(
                "LIVE OPEN holdes låst til den eksakte produkt-/margin-gaten er landet. "
                "AutoManage og CLOSE-beskyttelse kan aktiveres separat."
            ),
            key=f"td-autotrade-locked:{pilot_key}",
        )
        if st.button("Stopp AutoManage", key=f"td-stop-automanage:{pilot_key}", use_container_width=True):
            stop_strategy_enrollment_v2(pilot_key)
            st.success("AutoManage er slått av for denne strategien.")
            st.rerun()
        return

    seed = st.number_input(
        "Startkapital",
        min_value=1.0,
        value=float(DEFAULT_PILOT_SEED_CAPITAL),
        step=100.0,
        key=f"td-automanage-seed:{pilot_key}",
        help="Pilotens isolerte kapital. Realisert netto P/L legges til eller trekkes fra denne.",
    )
    acknowledge = st.checkbox(
        "Jeg vil at PriceGauger skal AutoManage denne eksakte LIVE-posisjonen.",
        key=f"td-automanage-ack:{pilot_key}",
    )
    if st.button(
        "Aktiver AutoManage",
        type="primary",
        disabled=not acknowledge,
        key=f"td-start-automanage:{pilot_key}",
        use_container_width=True,
    ):
        try:
            enroll_macd_flip_position_v2(
                observation,
                seed_capital=float(seed),
                currency=currency,
            )
        except Exception as exc:
            st.error(f"AutoManage kunne ikke aktiveres: {exc}")
            return
        st.success("30m MACD flip er koblet til den eksakte LIVE-posisjonen. LIVE re-entry er fortsatt låst.")
        st.rerun()


__all__ = ["AutoManagePanelSnapshotV2", "render_tradingdesk_automanage_panel_v2"]
