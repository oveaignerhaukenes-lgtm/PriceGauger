from __future__ import annotations

from typing import Any, Iterable

import streamlit as st

from ui_workspace_state_v2 import load_ui_workspace_state_v2, save_ui_workspace_state_v2


PAGE_KEY = "tradingdesk"
SCHEMA_VERSION = 1

MARKET_SESSION_KEY = "tradingdesk-v2-market"
TIMEFRAME_SESSION_KEY = "tradingdesk_timeframe"
MACD_TIMEFRAME_SESSION_KEY = "tradingdesk_macd_timeframe"
AUTO_REFRESH_SESSION_KEY = "tradingdesk_auto_refresh"
CONTROLS_WIDTH_SESSION_KEY = "tradingdesk-controls-width-pct"

# Explicit allow-list: UI workspace restore must never carry trading authority.
_SAFE_SESSION_KEYS = {
    "selected_market": MARKET_SESSION_KEY,
    "timeframe": TIMEFRAME_SESSION_KEY,
    "macd_timeframe": MACD_TIMEFRAME_SESSION_KEY,
    "auto_refresh": AUTO_REFRESH_SESSION_KEY,
    "controls_width_pct": CONTROLS_WIDTH_SESSION_KEY,
}


def _has_streamlit_run_context() -> bool:
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        return get_script_run_ctx(suppress_warning=True) is not None
    except Exception:
        return False


def _normalized_query_market() -> str:
    try:
        value = st.query_params.get("market", "")
    except Exception:
        return ""
    if isinstance(value, (list, tuple)):
        value = value[-1] if value else ""
    return str(value or "").strip()


def _safe_state_from_session(available_markets: set[str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for persisted_key, session_key in _SAFE_SESSION_KEYS.items():
        if session_key not in st.session_state:
            continue
        value = st.session_state.get(session_key)
        if persisted_key == "selected_market":
            market = str(value or "").strip()
            if market not in available_markets:
                continue
            result[persisted_key] = market
        elif persisted_key in {"timeframe", "macd_timeframe"}:
            result[persisted_key] = str(value or "").strip()
        elif persisted_key == "auto_refresh":
            result[persisted_key] = bool(value)
        elif persisted_key == "controls_width_pct":
            try:
                result[persisted_key] = int(value)
            except (TypeError, ValueError):
                continue
    return result


def restore_tradingdesk_workspace_state_v2(available_markets: Iterable[str]) -> str | None:
    """Restore safe TradingDesk view state without rewriting an unchanged widget key.

    Explicit `?market=` navigation wins, then an existing session value, then the
    persisted read-model state. The function may be called again after Streamlit has
    instantiated keyed widgets; unchanged values are therefore never assigned back
    into session_state.
    """
    if not _has_streamlit_run_context():
        return None

    markets = {str(item) for item in available_markets}
    if not markets:
        return None

    try:
        persisted = load_ui_workspace_state_v2(PAGE_KEY, schema_version=SCHEMA_VERSION)
    except Exception:
        persisted = None
    stored = {} if persisted is None else dict(persisted.state)

    current_market = str(st.session_state.get(MARKET_SESSION_KEY, "") or "").strip()
    requested_market = _normalized_query_market()
    if requested_market in markets:
        if current_market != requested_market:
            st.session_state[MARKET_SESSION_KEY] = requested_market
            current_market = requested_market
    elif current_market not in markets:
        stored_market = str(stored.get("selected_market") or "").strip()
        if stored_market in markets and current_market != stored_market:
            st.session_state[MARKET_SESSION_KEY] = stored_market
            current_market = stored_market

    for persisted_key, session_key in _SAFE_SESSION_KEYS.items():
        if persisted_key == "selected_market" or session_key in st.session_state:
            continue
        if persisted_key not in stored:
            continue
        value = stored[persisted_key]
        if persisted_key in {"timeframe", "macd_timeframe"}:
            value = str(value or "").strip()
            if not value:
                continue
        elif persisted_key == "auto_refresh":
            value = bool(value)
        elif persisted_key == "controls_width_pct":
            try:
                value = int(value)
            except (TypeError, ValueError):
                continue
        st.session_state[session_key] = value

    selected = str(st.session_state.get(MARKET_SESSION_KEY, "") or "").strip()
    return selected if selected in markets else None


def persist_tradingdesk_workspace_state_v2(available_markets: Iterable[str]) -> None:
    """Persist current safe widget values without mutating keyed Streamlit state."""
    if not _has_streamlit_run_context():
        return

    markets = {str(item) for item in available_markets}
    if not markets:
        return

    current = _safe_state_from_session(markets)
    if not current:
        return

    try:
        persisted = load_ui_workspace_state_v2(PAGE_KEY, schema_version=SCHEMA_VERSION)
    except Exception:
        persisted = None
    stored = {} if persisted is None else dict(persisted.state)
    if current == stored:
        return

    try:
        save_ui_workspace_state_v2(PAGE_KEY, current, schema_version=SCHEMA_VERSION)
    except Exception:
        # UI preference persistence must never break the trading workspace.
        pass


def sync_tradingdesk_workspace_state_v2(available_markets: Iterable[str]) -> str | None:
    """Restore when needed, then persist current safe state.

    Repeated calls are safe in the same Streamlit rerun because restore never writes
    an unchanged keyed-widget value back into session_state.
    """
    selected = restore_tradingdesk_workspace_state_v2(available_markets)
    persist_tradingdesk_workspace_state_v2(available_markets)
    return selected


__all__ = [
    "AUTO_REFRESH_SESSION_KEY",
    "CONTROLS_WIDTH_SESSION_KEY",
    "MACD_TIMEFRAME_SESSION_KEY",
    "MARKET_SESSION_KEY",
    "PAGE_KEY",
    "SCHEMA_VERSION",
    "TIMEFRAME_SESSION_KEY",
    "persist_tradingdesk_workspace_state_v2",
    "restore_tradingdesk_workspace_state_v2",
    "sync_tradingdesk_workspace_state_v2",
]
