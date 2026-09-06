from __future__ import annotations

from typing import Any, Mapping

import pandas as pd
import streamlit as st

from autotrader_live_close_v1 import code_gate_enabled_v1, load_live_close_config_v1
from autotrader_live_open_v2 import (
    LiveOpenConfigV2,
    code_gate_enabled_v2,
    load_live_open_config_v2,
    save_live_open_config_v2,
)
from autotrader_live_close_v1 import LiveCloseConfigV1, save_live_close_config_v1
from autotrader_manage_control_v1 import auto_manage_enabled_v1
from autotrader_manual_target_v2 import load_manual_target_quote_v2, request_manual_target_v2
from autotrader_operator_control_v1 import (
    MODE_PAUSED,
    MODE_PAUSING,
    MODE_RUNNING,
    MODE_STOPPED,
    MODE_STOPPING_CLOSE,
    close_and_stop_automanager_v1,
    effective_operator_control_v1,
    pause_automanager_v1,
    start_automanager_v1,
    stop_automanager_v1,
)
from autotrader_pnl_comparison_v2 import load_automanager_pnl_comparison_v2
from autotrader_risk_control_v2 import PositionObservationV2, _position_observations_v2
from autotrader_strategy_catalog_v2 import strategy_spec_v2
from autotrader_strategy_enrollment_v2 import (
    ENTRY_MODE_AUTO,
    EXECUTION_MODE_LIVE,
    StrategyEnrollmentV2,
    load_active_strategy_enrollments_v2,
    set_entry_mode_v2,
)
from database import connect
from saxo_provider import LIVE_BASE_URL, configured_client
from trading_desk_v2_context import TradingDeskV2Context


_CHART_CONTROL_JS = """
export default function(component) {
    const { data, parentElement, setTriggerValue } = component;
    parentElement.style.height = '0px';
    parentElement.style.minHeight = '0px';
    parentElement.style.overflow = 'visible';
    const chartId = String(data.chart_id || '');
    let cancelled = false;

    function button(text, background) {
        const item = document.createElement('button');
        item.type = 'button';
        item.textContent = text;
        Object.assign(item.style, {
            appearance: 'none', border: '1px solid rgba(255,255,255,.55)',
            borderRadius: '5px', padding: '3px 7px', minHeight: '25px',
            color: '#fff', background, boxShadow: '0 1px 4px rgba(15,23,42,.18)',
            font: '700 10px/1.15 system-ui,-apple-system,sans-serif',
            letterSpacing: '.01em', cursor: 'pointer', whiteSpace: 'nowrap',
            touchAction: 'manipulation',
        });
        return item;
    }

    function attach() {
        if (cancelled) return;
        const entry = window.__pricegaugerLightweightCharts?.get(chartId);
        if (!entry?.root || !document.body.contains(entry.root)) {
            window.setTimeout(attach, 120);
            return;
        }
        const root = entry.root;
        let top = root.querySelector(':scope > .pg-autotrader-chart-actions');
        if (!top) {
            top = document.createElement('div');
            top.className = 'pg-autotrader-chart-actions';
            Object.assign(top.style, {
                position: 'absolute', left: '8px', top: '6px', zIndex: '12',
                display: 'flex', gap: '4px', alignItems: 'center', pointerEvents: 'auto',
            });
            root.appendChild(top);
        }
        top.replaceChildren();
        if (entry.inspector) entry.inspector.style.top = '37px';

        const quote = data.quote || {};
        const enabled = Boolean(data.trade_enabled);
        const buyText = enabled && quote.ask_text ? `BUY ${quote.ask_text}` : 'BUY —';
        const sellText = enabled && quote.bid_text ? `SELL ${quote.bid_text}` : 'SELL —';
        const buy = button(buyText, '#dc2626');
        const sell = button(sellText, '#2563eb');
        buy.disabled = !enabled;
        sell.disabled = !enabled;
        if (!enabled) { buy.style.opacity = '.48'; sell.style.opacity = '.48'; }
        buy.onclick = (event) => {
            event.preventDefault(); event.stopPropagation();
            setTriggerValue('trade_target', { direction: 'LONG', nonce: Date.now() });
        };
        sell.onclick = (event) => {
            event.preventDefault(); event.stopPropagation();
            setTriggerValue('trade_target', { direction: 'SHORT', nonce: Date.now() });
        };
        top.append(buy, sell);

        let status = root.querySelector(':scope > .pg-autotrader-status-button');
        if (!status) {
            status = button('', '#15803d');
            status.className = 'pg-autotrader-status-button';
            Object.assign(status.style, {
                position: 'absolute', right: '66px', bottom: '34px', zIndex: '12',
                padding: '4px 8px', minHeight: '27px',
            });
            root.appendChild(status);
        }
        status.textContent = String(data.status_label || 'AutoManage OFF');
        status.style.background = data.armed_live ? '#b45309' : '#15803d';
        status.title = data.armed_live
            ? 'AutoTrader kjører LIVE. Trykk for monitor.'
            : 'AutoManager er ikke LIVE. Trykk for status og kontroller.';
        status.onclick = (event) => {
            event.preventDefault(); event.stopPropagation();
            setTriggerValue('monitor_open', { nonce: Date.now() });
        };
    }

    attach();
    return () => { cancelled = true; };
}
"""

_chart_control_component = st.components.v2.component(
    "pricegauger_tradingdesk_autotrader_chart_controls_v1",
    js=_CHART_CONTROL_JS,
    isolate_styles=False,
)


def _active_live(context: TradingDeskV2Context) -> StrategyEnrollmentV2 | None:
    matches = tuple(
        item for item in load_active_strategy_enrollments_v2()
        if item.enabled and item.execution_mode == EXECUTION_MODE_LIVE
        and int(item.market_id) == int(context.market_id)
        and (context.instrument_id is None or int(item.instrument_id) == int(context.instrument_id))
    )
    if len(matches) > 1:
        raise RuntimeError("more than one LIVE AutoManager controller matched TradingDesk product")
    return matches[0] if matches else None


def _client():
    client = configured_client()
    if client is None or client.base_url.rstrip("/").lower() != LIVE_BASE_URL.lower():
        return None
    return client


def _account_key(client, account_id: str) -> str:
    payload = client._get("port/v1/accounts/me")
    rows = payload.get("Data") or []
    if not isinstance(rows, list):
        raise RuntimeError("Saxo account list had invalid format")
    for row in rows:
        if isinstance(row, Mapping) and str(row.get("AccountId") or "") == str(account_id):
            key = str(row.get("AccountKey") or "").strip()
            if key:
                return key
    raise RuntimeError("could not resolve Saxo AccountKey")


def _observation(enrollment: StrategyEnrollmentV2, observations=None) -> PositionObservationV2 | None:
    if observations is None:
        client = _client()
        observations = () if client is None else _position_observations_v2(client)
    matches = tuple(
        item for item in observations
        if item.account_id == enrollment.account_id
        and int(item.uic) == int(enrollment.uic)
        and item.asset_type == enrollment.asset_type
    )
    if len(matches) > 1:
        raise RuntimeError("multiple Saxo positions matched AutoManager product")
    return matches[0] if matches else None


def _ensure_execution_ready(enrollment: StrategyEnrollmentV2) -> StrategyEnrollmentV2:
    current = enrollment
    if current.entry_mode != ENTRY_MODE_AUTO or not current.live_open_armed:
        current = set_entry_mode_v2(current.pilot_key, ENTRY_MODE_AUTO)
    save_live_open_config_v2(LiveOpenConfigV2(armed=True))
    save_live_close_config_v1(LiveCloseConfigV1(armed=True))
    return current


def _format_price(value: float) -> str:
    magnitude = abs(float(value))
    digits = 1 if magnitude >= 1000 else 2 if magnitude >= 10 else 3 if magnitude >= 1 else 4
    return f"{float(value):,.{digits}f}".replace(",", " ")


def _active_anomalies(enrollment: StrategyEnrollmentV2) -> tuple[dict[str, Any], ...]:
    try:
        with connect() as db:
            rows = db.execute(
                """
                SELECT kind, severity, details, order_id, external_reference, first_seen_at, last_seen_at
                FROM pg_v2_autotrader_execution_anomalies
                WHERE active = TRUE AND account_id = ? AND uic = ? AND asset_type = ?
                ORDER BY last_seen_at DESC LIMIT 10
                """,
                (enrollment.account_id, int(enrollment.uic), enrollment.asset_type),
            ).fetchall()
    except Exception:
        return ()
    return tuple(dict(row) for row in rows)


def _latest_macd_history(enrollment: StrategyEnrollmentV2) -> tuple[dict[str, Any], ...]:
    with connect() as db:
        rows = db.execute(
            """
            SELECT created_at, current_macd, current_signal, previous_macd, previous_signal,
                   outcome_reason, target_direction, signal
            FROM pg_v2_autotrader_strategy_evaluations
            WHERE pilot_key = ? AND current_macd IS NOT NULL AND current_signal IS NOT NULL
            ORDER BY created_at DESC LIMIT 80
            """,
            (enrollment.pilot_key,),
        ).fetchall()
    return tuple(reversed([dict(row) for row in rows]))


def _status(enrollment: StrategyEnrollmentV2, observation: PositionObservationV2 | None) -> tuple[bool, str, str]:
    operator = effective_operator_control_v1(enrollment, observation)
    manage = auto_manage_enabled_v1(enrollment)
    armed = bool(
        operator.mode == MODE_RUNNING
        and manage
        and enrollment.live_open_armed
        and load_live_open_config_v2().armed
        and load_live_close_config_v1().armed
        and code_gate_enabled_v2()
        and code_gate_enabled_v1()
        and not _active_anomalies(enrollment)
    )
    return armed, ("Armed LIVE" if armed else "AutoManage OFF"), operator.mode


def _request_chart_target(context: TradingDeskV2Context, direction: str) -> None:
    enrollment = _active_live(context)
    if enrollment is None:
        raise RuntimeError("ingen aktiv LIVE AutoManager-controller for chartet")
    if _active_anomalies(enrollment):
        raise RuntimeError("execution guard har en uavklart hendelse; BUY/SELL er blokkert")
    enrollment = _ensure_execution_ready(enrollment)
    request_manual_target_v2(enrollment, target_direction=direction)


def _render_realized_pnl(enrollment: StrategyEnrollmentV2) -> None:
    try:
        comparison = load_automanager_pnl_comparison_v2((enrollment,))
    except Exception as exc:
        st.caption(f"Realisert P/L-historikk venter: {exc}")
        return
    points = comparison.live_realized
    if len(points) < 2:
        st.caption("Realisert P/L: venter på første avsluttede handel.")
        return
    frame = pd.DataFrame(
        {"Realisert P/L %": [float(item.return_pct) for item in points]},
        index=[item.occurred_at for item in points],
    )
    st.line_chart(frame, height=140, use_container_width=True)


def _render_macd_logic(enrollment: StrategyEnrollmentV2) -> None:
    rows = _latest_macd_history(enrollment)
    if not rows:
        st.caption("Strategilogikk: venter på persisterte MACD-evalueringer.")
        return
    frame = pd.DataFrame(
        {
            "MACD": [float(item["current_macd"]) for item in rows],
            "Signal": [float(item["current_signal"]) for item in rows],
        },
        index=[item["created_at"] for item in rows],
    )
    st.line_chart(frame, height=180, use_container_width=True)
    latest = rows[-1]
    gap = float(latest["current_macd"]) - float(latest["current_signal"])
    prior_gap = None
    if latest.get("previous_macd") is not None and latest.get("previous_signal") is not None:
        prior_gap = float(latest["previous_macd"]) - float(latest["previous_signal"])
    trend = "ukjent"
    if prior_gap is not None:
        trend = "nærmer seg kryss" if abs(gap) < abs(prior_gap) else "øker avstanden"
    cols = st.columns(3)
    cols[0].metric("MACD-gap", f"{gap:+.6g}")
    cols[1].metric("Gap-utvikling", trend)
    cols[2].metric("Siste target", str(latest.get("target_direction") or "—"))
    st.caption(
        f"Siste motorutfall: {latest.get('outcome_reason') or '—'} · signal {latest.get('signal') or '—'}. "
        "Grafen viser persistert strategi-evidens; den sender ingen ordre."
    )


@st.dialog("AutoTrader monitor", width="large")
def _monitor_dialog(context: TradingDeskV2Context) -> None:
    enrollment = _active_live(context)
    if enrollment is None:
        st.success("AutoManage OFF")
        st.caption("Ingen aktiv LIVE-controller er knyttet til dette canonical produktet.")
        return
    client = _client()
    observations = () if client is None else _position_observations_v2(client)
    observation = _observation(enrollment, observations)
    armed, _, operator_mode = _status(enrollment, observation)
    spec = strategy_spec_v2(enrollment.strategy_key)

    st.markdown(f"**{'Armed LIVE' if armed else 'AutoManage OFF'} · {context.market_name}**")
    st.caption(f"{spec.label} · operator {operator_mode} · UIC {enrollment.uic} · {enrollment.asset_type}")

    metrics = st.columns(4)
    if observation is None:
        metrics[0].metric("Posisjon", "FLAT")
        metrics[1].metric("Amount", "—")
        metrics[2].metric("Saxo P/L", "—")
        metrics[3].metric("Pris", "—")
    else:
        direction = "LONG" if observation.direction.strip().lower() == "buy" else "SHORT"
        metrics[0].metric("Posisjon", direction)
        metrics[1].metric("Amount", f"{observation.amount:g}")
        metrics[2].metric("Saxo P/L", f"{observation.pnl_pct:+.2f}%")
        metrics[3].metric("Pris", _format_price(observation.current_price))
        st.caption(
            f"Snitt inngang {_format_price(observation.average_open_price)} · "
            f"net position {observation.net_position_id}"
        )

    anomalies = _active_anomalies(enrollment)
    if anomalies:
        latest = anomalies[0]
        st.error(
            f"Execution Guard: {latest['kind']} · {latest['severity']} · {latest.get('details') or ''}"
        )

    st.markdown("**P/L-utvikling · realisert**")
    _render_realized_pnl(enrollment)
    st.markdown("**Strategilogikk · MACD / signal**")
    _render_macd_logic(enrollment)

    pause_col, start_col, stop_col, close_col = st.columns(4, gap="small")
    pause = pause_col.button(
        "Pause", width="stretch", disabled=operator_mode in {MODE_PAUSING, MODE_PAUSED, MODE_STOPPING_CLOSE}
    )
    start = start_col.button(
        "Start", type="primary", width="stretch", disabled=armed or bool(anomalies)
    )
    stop = stop_col.button("Stop", width="stretch", disabled=operator_mode == MODE_STOPPED)
    close = close_col.button("Close position", width="stretch", disabled=observation is None)

    try:
        if pause:
            pause_automanager_v1(enrollment, observation)
            st.success("Pause satt: strategien er stoppet og går FLAT gjennom normal CLOSE-livssyklus.")
            st.rerun()
        if start:
            _ensure_execution_ready(enrollment)
            start_automanager_v1(enrollment, observation)
            st.success("AutoManager startet med samme controller og strategi.")
            st.rerun()
        if stop:
            stop_automanager_v1(enrollment)
            st.success("AutoManager stoppet. Saxo-posisjonen er ikke endret.")
            st.rerun()
        if close:
            close_and_stop_automanager_v1(enrollment, observation)
            st.success("Close position satt: AutoManager stopper og går FLAT via normal CLOSE-livssyklus.")
            st.rerun()
    except Exception as exc:
        st.error(f"AutoTrader-kontrollen ble blokkert: {exc}")

    st.caption(
        "Pause = FLAT og behold samme controller/strategi for senere Start. "
        "Stop = stopp management uten å endre posisjonen. Close position = FLAT og stopp."
    )


def render_autotrader_chart_controls_v1(context: TradingDeskV2Context) -> None:
    """Project AutoManager controls into the existing LIVE chart without order authority in JS."""
    enrollment = _active_live(context)
    quote = None
    observation = None
    armed = False
    status_label = "AutoManage OFF"
    enabled = False
    if enrollment is not None:
        client = _client()
        if client is not None:
            try:
                observations = _position_observations_v2(client)
                observation = _observation(enrollment, observations)
                account_key = _account_key(client, enrollment.account_id)
                quote = load_manual_target_quote_v2(enrollment, account_key=account_key)
            except Exception:
                quote = None
        try:
            armed, status_label, _ = _status(enrollment, observation)
        except Exception:
            armed, status_label = False, "AutoManage OFF"
        enabled = bool(quote is not None and not _active_anomalies(enrollment))

    payload = {
        "chart_id": f"TradingDeskLightweight:{context.market_name}",
        "trade_enabled": enabled,
        "armed_live": armed,
        "status_label": status_label,
        "quote": {} if quote is None else {
            "bid": quote.bid, "ask": quote.ask,
            "bid_text": _format_price(quote.bid), "ask_text": _format_price(quote.ask),
        },
    }
    result = _chart_control_component(
        key=f"td-autotrader-chart-controls:{context.market_id}:{context.instrument_id}",
        data=payload,
        height=0,
        on_trade_target_change=lambda: None,
        on_monitor_open_change=lambda: None,
    )
    trade = getattr(result, "trade_target", None)
    if isinstance(trade, Mapping) and str(trade.get("direction") or "") in {"LONG", "SHORT"}:
        try:
            _request_chart_target(context, str(trade["direction"]))
        except Exception as exc:
            st.toast(f"BUY/SELL blokkert: {exc}", icon="⚠️")
        else:
            st.toast(f"Mål satt: {trade['direction']} · execution-motoren har overtatt.")
    if getattr(result, "monitor_open", None):
        _monitor_dialog(context)


__all__ = ["render_autotrader_chart_controls_v1"]
