from __future__ import annotations

from threading import Lock

from database import connect, using_postgres


DEFAULT_HARD_STOP_PCT = -2.0
_SCHEMA_LOCK = Lock()
_SCHEMA_INITIALIZED = False


def ensure_autotrader_schema_v2() -> None:
    """Initialize the complete PostgreSQL persistence boundary for AutoTrader v2.

    Runtime services own schema initialization. Streamlit read/write surfaces must
    never perform DDL as a side effect of rendering.
    """
    global _SCHEMA_INITIALIZED
    if not using_postgres():
        raise RuntimeError("AutoTrader v2 requires PostgreSQL")
    with _SCHEMA_LOCK:
        if _SCHEMA_INITIALIZED:
            return
        _ensure_autotrader_schema_v2_unlocked()
        _SCHEMA_INITIALIZED = True


def _ensure_autotrader_schema_v2_unlocked() -> None:
    statements = (
        """
        CREATE TABLE IF NOT EXISTS pg_v2_autotrader_risk_config (
            config_id SMALLINT PRIMARY KEY CHECK (config_id = 1),
            enabled BOOLEAN NOT NULL,
            hard_stop_pct DOUBLE PRECISION NOT NULL,
            trailing_enabled BOOLEAN NOT NULL,
            trailing_activation_pct DOUBLE PRECISION NOT NULL,
            trailing_drawdown_pct DOUBLE PRECISION NOT NULL,
            fixed_take_profit_enabled BOOLEAN NOT NULL,
            fixed_take_profit_pct DOUBLE PRECISION NOT NULL,
            max_price_delay_minutes INTEGER NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        """
        INSERT INTO pg_v2_autotrader_risk_config
            (config_id, enabled, hard_stop_pct, trailing_enabled,
             trailing_activation_pct, trailing_drawdown_pct,
             fixed_take_profit_enabled, fixed_take_profit_pct,
             max_price_delay_minutes)
        VALUES (1, TRUE, -2.0, TRUE, 2.0, 0.5, FALSE, 5.0, 0)
        ON CONFLICT (config_id) DO NOTHING
        """,
        """
        CREATE TABLE IF NOT EXISTS pg_v2_autotrader_risk_state (
            account_id TEXT NOT NULL,
            net_position_id TEXT NOT NULL,
            uic BIGINT NOT NULL,
            asset_type TEXT NOT NULL,
            direction TEXT NOT NULL,
            amount DOUBLE PRECISION NOT NULL,
            average_open_price DOUBLE PRECISION NOT NULL,
            current_price DOUBLE PRECISION NOT NULL,
            pnl_pct DOUBLE PRECISION NOT NULL,
            high_water_pct DOUBLE PRECISION NOT NULL,
            trailing_floor_pct DOUBLE PRECISION,
            price_delay_minutes INTEGER NOT NULL,
            can_be_closed BOOLEAN NOT NULL,
            calculation_reliability TEXT NOT NULL,
            is_market_open BOOLEAN NOT NULL DEFAULT FALSE,
            non_tradable_reason TEXT NOT NULL DEFAULT '',
            last_action TEXT NOT NULL,
            last_reason TEXT NOT NULL,
            triggered_reason TEXT,
            triggered_at TIMESTAMPTZ,
            active BOOLEAN NOT NULL DEFAULT TRUE,
            last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY(account_id, net_position_id)
        )
        """,
        "ALTER TABLE pg_v2_autotrader_risk_state ADD COLUMN IF NOT EXISTS is_market_open BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE pg_v2_autotrader_risk_state ADD COLUMN IF NOT EXISTS non_tradable_reason TEXT NOT NULL DEFAULT ''",
        """
        CREATE TABLE IF NOT EXISTS pg_v2_autotrader_risk_events (
            event_id UUID PRIMARY KEY,
            account_id TEXT NOT NULL,
            net_position_id TEXT NOT NULL,
            uic BIGINT NOT NULL,
            asset_type TEXT NOT NULL,
            direction TEXT NOT NULL,
            reason TEXT NOT NULL,
            pnl_pct DOUBLE PRECISION NOT NULL,
            high_water_pct DOUBLE PRECISION NOT NULL,
            trailing_floor_pct DOUBLE PRECISION,
            hard_stop_pct DOUBLE PRECISION NOT NULL,
            trailing_activation_pct DOUBLE PRECISION NOT NULL,
            trailing_drawdown_pct DOUBLE PRECISION NOT NULL,
            fixed_take_profit_pct DOUBLE PRECISION NOT NULL,
            price_delay_minutes INTEGER NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS pg_v2_autotrader_risk_events_position_time_idx
        ON pg_v2_autotrader_risk_events(account_id, net_position_id, created_at DESC)
        """,
        """
        CREATE TABLE IF NOT EXISTS pg_v2_autotrader_managed_positions (
            account_id TEXT NOT NULL,
            net_position_id TEXT NOT NULL,
            uic BIGINT NOT NULL,
            asset_type TEXT NOT NULL,
            direction TEXT NOT NULL,
            amount DOUBLE PRECISION NOT NULL,
            average_open_price DOUBLE PRECISION NOT NULL,
            managed BOOLEAN NOT NULL DEFAULT TRUE,
            enrolled_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY(account_id, net_position_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS pg_v2_autotrader_live_close_config (
            config_id SMALLINT PRIMARY KEY CHECK (config_id = 1),
            armed BOOLEAN NOT NULL DEFAULT FALSE,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        """
        INSERT INTO pg_v2_autotrader_live_close_config (config_id, armed)
        VALUES (1, FALSE)
        ON CONFLICT (config_id) DO NOTHING
        """,
        """
        CREATE TABLE IF NOT EXISTS pg_v2_autotrader_live_close_attempts (
            event_id UUID PRIMARY KEY,
            account_id TEXT NOT NULL,
            net_position_id TEXT NOT NULL,
            uic BIGINT NOT NULL,
            asset_type TEXT NOT NULL,
            close_side TEXT NOT NULL,
            amount DOUBLE PRECISION NOT NULL,
            external_reference TEXT NOT NULL,
            status TEXT NOT NULL,
            order_id TEXT,
            precheck_result TEXT,
            error_message TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS pg_v2_autotrader_live_close_status_idx
        ON pg_v2_autotrader_live_close_attempts(status, updated_at DESC)
        """,
    )
    with connect() as db:
        for statement in statements:
            db.execute(statement)
