from __future__ import annotations

from dataclasses import dataclass

import streamlit as st

from autotrader_activity_log_v2 import load_automanager_activity_log_v2
from autotrader_automanage_container_v2 import AutoManageProductV2, resolve_saxo_automanage_product_v2
from autotrader_managed_positions_v1 import is_position_managed_v1
from autotrader_manual_entry_adoption_v2 import adopt_user_confirmed_position_v2
from autotrader_pnl_chart_v2 import build_automanager_pnl_figure_v2
from autotrader_pnl_comparison_v2 import load_automanager_pnl_comparison_v2
from autotrader_pilot_equity_v2 import DEFAULT_PILOT_SEED_CAPITAL, load_pilot_equity_v2
from autotrader_risk_control_v2 import PositionObservationV2, _position_observations_v2
from autotrader_shadow_benchmark_v2 import load_shadow_benchmark_snapshots_v2
from autotrader_strategy_catalog_v2 import (
    AUTOTRADER_STRATEGIES_V2,
    AutoTraderStrategySpecV2,
    strategy_spec_v2,
)
from autotrader_strategy_enrollment_v2 import (
    EXECUTION_MODE_LIVE,
    EXECUTION_MODE_SHADOW,
    StrategyEnrollmentV2,
    enroll_strategy_position_v2,
    load_active_strategy_enrollments_v2,
    load_product_strategy_enrollments_v2,
    load_strategy_enrollment_v2,
    stop_strategy_enrollment_v2,
)
from database import connect, using_postgres
from saxo_provider import LIVE_BASE_URL, configured_client
from time_display_v2 import localize_plotly_figure_v2, oslo_label
from trading_desk_v2_context import TradingDeskV2Context
from tradingdesk_autotrade_entry_gate_v2 import ENTRY_MODE_LABELS, render_tradingdesk_autotrade_entry_gate_v2


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
) -> tuple[tuple[PositionObservationV2, AutoManageProductV2], ...]:
    matches: list[tuple[PositionObservationV2, AutoManageProductV2]] = []
    for observation in observations:
        try:
            product = resolve_saxo_automanage_product_v2(observation)
        except Exception:
            continue
        if int(product.market_id) == int(context.market_id):
            matches.append((observation, product))
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
            FROM pg_v2_autotrader_strategy_evaluations
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


def _position_label(item: tuple[PositionObservationV2, AutoManageProductV2]) -> str:
    observation, _ = item
    side = "LONG" if observation.direction.strip().lower() == "buy" else "SHORT"
    return f"{side} · {observation.asset_type} · UIC {observation.uic} · {observation.pnl_pct:+.2f}%"


def _metric_money(value: float | None, currency: str) -> str:
    if value is None:
        return "—"
    return f"{value:,.2f} {currency}".replace(",", " ")


def _strategy_label(spec: AutoTraderStrategySpecV2) -> str:
    return spec.label


def _default_shadow_index(candidates: tuple[AutoTraderStrategySpecV2, ...]) -> int:
    for index, item in enumerate(candidates):
        if "long-short" in item.key:
            return index
    return 0


def _render_strategy_scorecards(enrollments: tuple[StrategyEnrollmentV2, ...]) -> None:
    if not enrollments:
        return
    groups: dict[tuple[str, int, str, int], list[StrategyEnrollmentV2]] = {}
    for enrollment in enrollments:
        key = (
            enrollment.account_id,
            int(enrollment.uic),
            enrollment.asset_type,
            int(enrollment.instrument_id),
        )
        groups.setdefault(key, []).append(enrollment)

    st.markdown("**LIVE / SHADOW · samme startgrunnlag**")
    for key, group in groups.items():
        try:
            snapshots = load_shadow_benchmark_snapshots_v2(tuple(group))
        except Exception as exc:
            st.caption(f"UIC {key[1]} · paper-benchmark venter: {exc}")
            continue
        if len(groups) > 1:
            st.caption(f"UIC {key[1]} · {key[2]}")
        columns = st.columns(max(1, len(snapshots)))
        for column, item in zip(columns, snapshots):
            spec = strategy_spec_v2(item.strategy_key)
            mode = "LIVE-strategi" if item.execution_mode == EXECUTION_MODE_LIVE else "SHADOW"
            with column:
                st.caption(mode)
                st.markdown(f"**{spec.label}**")
                if item.evaluated_bars == 0:
                    st.metric("Paper P/L", "venter")
                    st.caption("Første nye lukkede 30m-bar etter enrollment starter sammenligningen.")
                    continue
                st.metric("Paper P/L", f"{item.return_pct:+.2f}%")
                st.caption(
                    f"{item.position_state} · {item.transitions} skifter · {item.evaluated_bars} bars"
                )
    st.caption(
        "Paper-replay bruker samme observerte startposisjon og samme exact canonical 30m-prisbane. "
        "Ingen spread/slippage/margin modelleres; faktisk Saxo-P/L føres separat i LIVE-ledgeren."
    )


def _render_automanager_activity_log_v2(
    enrollment: StrategyEnrollmentV2,
    *,
    observations: tuple[PositionObservationV2, ...] | None = None,
) -> None:
    observed_direction_override = None
    exact_close_authority_override = None
    if observations is not None:
        observation = next(
            (
                item
                for item in observations
                if item.account_id == enrollment.account_id
                and int(item.uic) == int(enrollment.uic)
                and item.asset_type == enrollment.asset_type
            ),
            None,
        )
        if observation is None:
            observed_direction_override = "FLAT"
        else:
            observed_direction_override = (
                "LONG" if observation.direction.strip().lower() == "buy" else "SHORT"
            )
            exact_close_authority_override = is_position_managed_v1(observation)
    try:
        activity = load_automanager_activity_log_v2(
            enrollment,
            limit=8,
            observed_direction_override=observed_direction_override,
            exact_close_authority_override=exact_close_authority_override,
        )
    except Exception as exc:
        st.caption(f"Hendelsesloggen venter: {exc}")
        return

    st.markdown("**Hendelser og neste status**")
    st.info(f"**Status nå: {activity.lifecycle_status}**\n\nNeste: {activity.next_step}")
    with st.expander(f"Siste hendelser ({len(activity.events)})", expanded=True):
        for event in activity.events:
            with st.container(border=True):
                st.caption(f"{oslo_label(event.occurred_at)} · {event.engine}")
                st.markdown(f"**{event.title}**")
                details = [event.detail, event.status]
                if event.realized_net_pnl is not None:
                    currency = event.currency or ""
                    details.append(f"Realisert netto {event.realized_net_pnl:+.2f} {currency}".strip())
                st.caption(" · ".join(item for item in details if item))


def render_tradingdesk_automanage_pnl_chart_v2(
    context: TradingDeskV2Context,
    *,
    observations: tuple[PositionObservationV2, ...] | None = None,
) -> None:
    """Render the bottom-of-workspace LIVE/paper comparison on explicit contracts."""
    if not using_postgres():
        return
    try:
        enrollments = tuple(
            item
            for item in load_active_strategy_enrollments_v2()
            if int(item.market_id) == int(context.market_id)
        )
    except Exception as exc:
        st.caption(f"P/L-grafen venter: {exc}")
        return
    if not enrollments:
        return

    groups: dict[tuple[str, int, str, int], list[StrategyEnrollmentV2]] = {}
    for enrollment in enrollments:
        key = (
            enrollment.account_id,
            int(enrollment.uic),
            enrollment.asset_type,
            int(enrollment.instrument_id),
        )
        groups.setdefault(key, []).append(enrollment)

    st.divider()
    st.markdown("**P/L · LIVE og modellene**")
    for key, group in groups.items():
        try:
            comparison = load_automanager_pnl_comparison_v2(tuple(group))
            figure = build_automanager_pnl_figure_v2(comparison)
            localize_plotly_figure_v2(figure)
        except Exception as exc:
            st.caption(f"UIC {key[1]} · P/L-sammenligning venter: {exc}")
            continue
        if len(groups) > 1:
            st.caption(f"UIC {key[1]} · {key[2]}")
        st.plotly_chart(
            figure,
            width="stretch",
            key=f"td-automanage-pnl:{key[0]}:{key[1]}:{key[2]}:{key[3]}",
            config={"displaylogo": False, "scrollZoom": True},
        )
        live = next((item for item in group if item.execution_mode == EXECUTION_MODE_LIVE), None)
        if live is not None:
            _render_automanager_activity_log_v2(live, observations=observations)
    st.caption(
        "Øverst vises bare faktisk, avstemt og realisert netto Saxo-P/L; åpen urealisert P/L estimeres ikke. "
        "Nederst vises long/flat, short/flat og MACD Switch som paper-replay på samme observerte startposisjon "
        "og samme lukkede canonical 30m-prisbane. Paperlinjene modellerer ikke spread, slippage eller margin."
    )


def render_tradingdesk_automanage_panel_v2(
    context: TradingDeskV2Context,
) -> tuple[PositionObservationV2, ...] | None:
    """Wide AutoManager workspace for strategy-neutral product management."""
    st.markdown("**AutoManager**")
    st.caption("Eksakt LIVE-produkt · strategivalg · separat execution-policy")

    if not using_postgres():
        st.info("AutoManager krever PostgreSQL-runtime.")
        return None

    client = configured_client()
    environment_ok = bool(client and client.base_url.rstrip("/").lower() == LIVE_BASE_URL.lower())
    if client is None or not environment_ok:
        st.info("Saxo LIVE er ikke tilgjengelig i web-runtime.")
        return None

    # This stays visible even while the strategy is FLAT, unlike the position
    # enrollment controls below which naturally require a currently open position.
    render_tradingdesk_autotrade_entry_gate_v2(context)
    try:
        context_enrollments = tuple(
            item
            for item in load_active_strategy_enrollments_v2()
            if int(item.market_id) == int(context.market_id)
        )
    except Exception:
        context_enrollments = ()
    if context_enrollments:
        st.divider()
        _render_strategy_scorecards(context_enrollments)
    st.divider()

    try:
        observations = _position_observations_v2(client)
        candidates = _candidate_positions_for_context(context, observations)
    except Exception as exc:
        st.warning(f"Kunne ikke lese LIVE-posisjonene: {exc}")
        return None

    if not candidates:
        st.caption("Ingen åpen LIVE-posisjon matcher dette canonical markedet. Aktiv pilot/execution-policy og strategitest over forblir synlig.")
        return observations

    observation, product = st.selectbox(
        "Åpen posisjon",
        candidates,
        format_func=_position_label,
        key=f"td-automanage-position:{context.market_id}",
    )
    currency = _account_currency(client, observation.account_id) or "NOK"

    side = "LONG" if observation.direction.strip().lower() == "buy" else "SHORT"
    c1, c2 = st.columns(2)
    c1.metric("Posisjon", side)
    c2.metric("P/L", f"{observation.pnl_pct:+.2f}%")
    c3, c4 = st.columns(2)
    c3.metric("Åpnet", f"{observation.average_open_price:g}")
    c4.metric("Nå", f"{observation.current_price:g}")
    st.caption(
        f"Amount {observation.amount:g} · {product.provider.upper()} UIC {observation.uic} · "
        f"{observation.asset_type} · canonical instrument_id {product.instrument_id}"
    )

    strategy = st.selectbox(
        "LIVE-strategi",
        AUTOTRADER_STRATEGIES_V2,
        format_func=_strategy_label,
        key=f"td-automanage-strategy:{product.product_key}",
        help="Strategien som får faktisk management-authority på den eksakte Saxo-posisjonen.",
    )
    pilot_key = product.pilot_key(strategy.key)
    snapshot = _snapshot(observation, pilot_key=pilot_key, currency=currency)

    try:
        product_enrollments = load_product_strategy_enrollments_v2(
            account_id=observation.account_id,
            uic=observation.uic,
            asset_type=observation.asset_type,
        )
    except Exception:
        product_enrollments = ()
    if product_enrollments:
        state_text = " · ".join(
            f"{item.strategy_key}: {'LIVE' if item.execution_mode == EXECUTION_MODE_LIVE else 'shadow'}"
            for item in product_enrollments
        )
        st.caption(f"Aktive piloter: {state_text}")

    active = bool(snapshot.enrollment and snapshot.enrollment.enabled)
    if active:
        e1, e2 = st.columns(2)
        e1.metric("Pilotkapital", _metric_money(snapshot.equity, currency))
        e2.metric("Realisert", _metric_money(snapshot.realized_net_pnl, currency))
        status_bits = [snapshot.enrollment.execution_mode, f"trades {snapshot.realized_events}"]
        if snapshot.enrollment.execution_mode == EXECUTION_MODE_LIVE:
            status_bits.append(ENTRY_MODE_LABELS.get(snapshot.enrollment.entry_mode, snapshot.enrollment.entry_mode))
        if snapshot.last_action:
            status_bits.append(f"siste {snapshot.last_action}")
        if snapshot.last_signal:
            status_bits.append(f"signal {snapshot.last_signal}")
        st.caption(" · ".join(status_bits))
        if snapshot.last_outcome:
            st.caption(f"Runtime: {snapshot.last_outcome}")

        if snapshot.enrollment.execution_mode == EXECUTION_MODE_LIVE:
            if not is_position_managed_v1(observation):
                st.warning(
                    "Denne Saxo-posisjonen observeres av piloten, men den eksakte amount/open-basen har ikke "
                    "CLOSE-authority. En strategi-exit vil være fail-closed til posisjonen er overtatt."
                )
                adopt_ack = st.checkbox(
                    "Jeg vil at den aktive piloten skal forvalte og kunne lukke akkurat denne posisjonen.",
                    key=f"td-adopt-position-ack:{snapshot.pilot_key}:{observation.net_position_id}",
                    help="Sender ingen ordre. Den registrerer bare eksakt Saxo-basis som AutoManaged.",
                )
                if st.button(
                    "Overta denne posisjonen",
                    disabled=not adopt_ack,
                    key=f"td-adopt-position:{snapshot.pilot_key}:{observation.net_position_id}",
                    width="stretch",
                ):
                    try:
                        adopt_user_confirmed_position_v2(snapshot.enrollment, observation)
                    except Exception as exc:
                        st.error(f"Posisjonen kunne ikke overtas: {exc}")
                    else:
                        st.success("Posisjonen er overtatt med eksakt CLOSE-authority. Ingen ordre ble sendt.")
                        st.rerun()
            st.caption("Execution-adferd og gates for denne piloten konfigureres i seksjonen over.")
        if st.button("Stopp denne piloten", key=f"td-stop-automanage:{pilot_key}", width="stretch"):
            stop_strategy_enrollment_v2(pilot_key)
            st.success("Piloten er slått av.")
            st.rerun()
        return observations

    seed = st.number_input(
        "Startkapital",
        min_value=1.0,
        value=float(DEFAULT_PILOT_SEED_CAPITAL),
        step=100.0,
        key=f"td-automanage-seed:{product.product_key}",
        help="Isolert pilotkapital. LIVE bruker senere realisert netto P/L til compounding.",
    )
    shadow_candidates = tuple(item for item in AUTOTRADER_STRATEGIES_V2 if item.key != strategy.key)
    compare_shadow = st.checkbox(
        "Kjør én shadow-strategi for direkte sammenligning",
        value=True,
        key=f"td-automanage-shadow:{product.product_key}:{strategy.key}",
        help="Shadow får samme observerte startposisjon og canonical 30m-bars, men ingen Saxo order-authority.",
    )
    shadow_strategy = None
    if compare_shadow and shadow_candidates:
        shadow_strategy = st.selectbox(
            "SHADOW-strategi",
            shadow_candidates,
            index=_default_shadow_index(shadow_candidates),
            format_func=_strategy_label,
            key=f"td-automanage-shadow-strategy:{product.product_key}:{strategy.key}",
            help="For long/flat LIVE velges long/short flip som standard for morgendagens A/B-test.",
        )
    acknowledge = st.checkbox(
        "Jeg vil at PriceGauger skal AutoManage denne eksakte LIVE-posisjonen med valgt strategi.",
        key=f"td-automanage-ack:{product.product_key}:{strategy.key}",
    )
    if st.button(
        "Aktiver AutoManager",
        type="primary",
        disabled=not acknowledge,
        key=f"td-start-automanage:{product.product_key}:{strategy.key}",
        width="stretch",
    ):
        try:
            enroll_strategy_position_v2(
                observation,
                strategy_key=strategy.key,
                execution_mode=EXECUTION_MODE_LIVE,
                seed_capital=float(seed),
                currency=currency,
            )
            if shadow_strategy is not None:
                enroll_strategy_position_v2(
                    observation,
                    strategy_key=shadow_strategy.key,
                    execution_mode=EXECUTION_MODE_SHADOW,
                    seed_capital=float(seed),
                    currency=currency,
                )
        except Exception as exc:
            st.error(f"AutoManager kunne ikke aktiveres: {exc}")
            return observations
        shadow_text = (
            f"; {shadow_strategy.label} er startet som SHADOW."
            if shadow_strategy is not None
            else "."
        )
        st.success(
            f"{strategy.label} er koblet LIVE til produktcontaineren{shadow_text} "
            "Standard er Manage-only; velg Full auto hvis PG også skal gjøre re-entry etter strategi-exit."
        )
        st.rerun()
    return observations


__all__ = [
    "AutoManagePanelSnapshotV2",
    "render_tradingdesk_automanage_panel_v2",
    "render_tradingdesk_automanage_pnl_chart_v2",
]
