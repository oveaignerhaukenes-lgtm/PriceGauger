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
        """
        CREATE TABLE IF NOT EXISTS pg_v2_autotrader_live_pilot_state (
            pilot_key TEXT PRIMARY KEY,
            strategy_key TEXT NOT NULL,
            account_id TEXT NOT NULL,
            net_position_id TEXT NOT NULL,
            uic BIGINT NOT NULL,
            asset_type TEXT NOT NULL,
            market_id BIGINT NOT NULL REFERENCES pg_v2_markets(market_id),
            instrument_id BIGINT NOT NULL REFERENCES pg_v2_instruments(instrument_id),
            market_name TEXT NOT NULL,
            last_evaluated_bar_time TIMESTAMPTZ,
            reversal_pending BOOLEAN NOT NULL DEFAULT FALSE,
            pending_intent_id UUID,
            pending_signal_at TIMESTAMPTZ,
            pending_signal TEXT,
            pending_target_direction TEXT,
            pending_previous_macd DOUBLE PRECISION,
            pending_previous_signal DOUBLE PRECISION,
            pending_current_macd DOUBLE PRECISION,
            pending_current_signal DOUBLE PRECISION,
            pending_target_fraction DOUBLE PRECISION,
            pending_budget_amount DOUBLE PRECISION,
            pending_budget_currency TEXT,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS pg_v2_autotrader_live_pilot_evaluations (
            evaluation_id UUID PRIMARY KEY,
            pilot_key TEXT NOT NULL,
            strategy_key TEXT NOT NULL,
            account_id TEXT NOT NULL,
            net_position_id TEXT NOT NULL,
            uic BIGINT NOT NULL,
            asset_type TEXT NOT NULL,
            market_id BIGINT NOT NULL REFERENCES pg_v2_markets(market_id),
            instrument_id BIGINT NOT NULL REFERENCES pg_v2_instruments(instrument_id),
            market_name TEXT NOT NULL,
            canonical_source_fingerprint TEXT NOT NULL,
            latest_closed_bar_time TIMESTAMPTZ NOT NULL,
            observed_direction TEXT NOT NULL,
            observed_fraction DOUBLE PRECISION NOT NULL,
            outcome_reason TEXT NOT NULL,
            intent_id UUID,
            signal_at TIMESTAMPTZ,
            signal TEXT,
            target_direction TEXT,
            previous_macd DOUBLE PRECISION,
            previous_signal DOUBLE PRECISION,
            current_macd DOUBLE PRECISION,
            current_signal DOUBLE PRECISION,
            requested_action TEXT,
            prior_direction TEXT,
            desired_direction TEXT,
            prior_fraction DOUBLE PRECISION,
            target_fraction DOUBLE PRECISION,
            delta_fraction DOUBLE PRECISION,
            decision_rationale TEXT,
            reversal_pending BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS pg_v2_autotrader_live_pilot_eval_time_idx
        ON pg_v2_autotrader_live_pilot_evaluations(pilot_key, created_at DESC)
        """,
        """
        CREATE TABLE IF NOT EXISTS pg_v2_autotrader_pilot_equity_state (
            pilot_key TEXT PRIMARY KEY,
            seed_capital DOUBLE PRECISION NOT NULL CHECK (seed_capital > 0),
            currency TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS pg_v2_autotrader_pilot_equity_events (
            event_id UUID PRIMARY KEY,
            pilot_key TEXT NOT NULL REFERENCES pg_v2_autotrader_pilot_equity_state(pilot_key),
            source_kind TEXT NOT NULL,
            source_reference TEXT NOT NULL,
            realized_net_pnl DOUBLE PRECISION NOT NULL,
            currency TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE(pilot_key, source_kind, source_reference)
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS pg_v2_autotrader_pilot_equity_event_time_idx
        ON pg_v2_autotrader_pilot_equity_events(pilot_key, created_at ASC)
        """,
        """
        CREATE TABLE IF NOT EXISTS pg_v2_autotrader_strategy_enrollments (
            pilot_key TEXT PRIMARY KEY REFERENCES pg_v2_autotrader_pilot_equity_state(pilot_key),
            strategy_key TEXT NOT NULL,
            execution_mode TEXT NOT NULL DEFAULT 'LIVE_MANAGE',
            account_id TEXT NOT NULL,
            anchor_net_position_id TEXT NOT NULL,
            uic BIGINT NOT NULL,
            asset_type TEXT NOT NULL,
            market_id BIGINT NOT NULL REFERENCES pg_v2_markets(market_id),
            instrument_id BIGINT NOT NULL REFERENCES pg_v2_instruments(instrument_id),
            market_name TEXT NOT NULL,
            enabled BOOLEAN NOT NULL DEFAULT TRUE,
            live_open_armed BOOLEAN NOT NULL DEFAULT FALSE,
            enrolled_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE(account_id, uic, asset_type, strategy_key)
        )
        """,
        "ALTER TABLE pg_v2_autotrader_strategy_enrollments ADD COLUMN IF NOT EXISTS execution_mode TEXT NOT NULL DEFAULT 'LIVE_MANAGE'",
        """
        CREATE INDEX IF NOT EXISTS pg_v2_autotrader_strategy_enrollment_active_idx
        ON pg_v2_autotrader_strategy_enrollments(enabled, updated_at DESC)
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS pg_v2_autotrader_one_live_strategy_per_product_idx
        ON pg_v2_autotrader_strategy_enrollments(account_id, uic, asset_type)
        WHERE enabled = TRUE AND execution_mode = 'LIVE_MANAGE'
        """,
        """
        CREATE TABLE IF NOT EXISTS pg_v2_autotrader_strategy_runtime_state (
            pilot_key TEXT PRIMARY KEY REFERENCES pg_v2_autotrader_strategy_enrollments(pilot_key),
            strategy_key TEXT NOT NULL,
            last_evaluated_bar_time TIMESTAMPTZ,
            pending_intent_id UUID,
            pending_signal_at TIMESTAMPTZ,
            pending_signal TEXT,
            pending_target_direction TEXT,
            pending_previous_macd DOUBLE PRECISION,
            pending_previous_signal DOUBLE PRECISION,
            pending_current_macd DOUBLE PRECISION,
            pending_current_signal DOUBLE PRECISION,
            pending_budget_amount DOUBLE PRECISION,
            pending_budget_currency TEXT,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS pg_v2_autotrader_strategy_evaluations (
            evaluation_id UUID PRIMARY KEY,
            pilot_key TEXT NOT NULL REFERENCES pg_v2_autotrader_strategy_enrollments(pilot_key),
            strategy_key TEXT NOT NULL,
            latest_closed_bar_time TIMESTAMPTZ NOT NULL,
            observed_net_position_id TEXT,
            observed_direction TEXT NOT NULL,
            outcome_reason TEXT NOT NULL,
            intent_id UUID,
            signal_at TIMESTAMPTZ,
            signal TEXT,
            target_direction TEXT,
            previous_macd DOUBLE PRECISION,
            previous_signal DOUBLE PRECISION,
            current_macd DOUBLE PRECISION,
            current_signal DOUBLE PRECISION,
            requested_action TEXT,
            desired_direction TEXT,
            budget_amount DOUBLE PRECISION,
            budget_currency TEXT,
            execution_request_id UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS pg_v2_autotrader_strategy_eval_time_idx
        ON pg_v2_autotrader_strategy_evaluations(pilot_key, created_at DESC)
        """,
        """
        CREATE TABLE IF NOT EXISTS pg_v2_autotrader_execution_requests (
            request_id UUID PRIMARY KEY,
            evaluation_id UUID NOT NULL REFERENCES pg_v2_autotrader_strategy_evaluations(evaluation_id),
            pilot_key TEXT NOT NULL REFERENCES pg_v2_autotrader_strategy_enrollments(pilot_key),
            strategy_key TEXT NOT NULL,
            action TEXT NOT NULL CHECK (action IN ('OPEN', 'CLOSE')),
            desired_direction TEXT NOT NULL CHECK (desired_direction IN ('FLAT', 'LONG', 'SHORT')),
            signal_at TIMESTAMPTZ NOT NULL,
            signal TEXT NOT NULL,
            account_id TEXT NOT NULL,
            observed_net_position_id TEXT,
            observed_direction TEXT NOT NULL,
            observed_amount DOUBLE PRECISION,
            observed_average_open_price DOUBLE PRECISION,
            uic BIGINT NOT NULL,
            asset_type TEXT NOT NULL,
            market_id BIGINT NOT NULL REFERENCES pg_v2_markets(market_id),
            instrument_id BIGINT NOT NULL REFERENCES pg_v2_instruments(instrument_id),
            budget_amount DOUBLE PRECISION NOT NULL CHECK (budget_amount >= 0),
            budget_currency TEXT NOT NULL,
            status TEXT NOT NULL,
            block_reason TEXT,
            order_id TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS pg_v2_autotrader_execution_request_status_idx
        ON pg_v2_autotrader_execution_requests(status, action, created_at ASC)
        """,
        """
        CREATE TABLE IF NOT EXISTS pg_v2_autotrader_equity_reconciliations (
            close_event_id UUID PRIMARY KEY REFERENCES pg_v2_autotrader_live_close_attempts(event_id),
            pilot_key TEXT NOT NULL REFERENCES pg_v2_autotrader_pilot_equity_state(pilot_key),
            closing_external_reference TEXT NOT NULL,
            closed_position_unique_ids TEXT NOT NULL,
            closing_position_ids TEXT NOT NULL,
            gross_pnl_base DOUBLE PRECISION NOT NULL,
            opening_cost_base DOUBLE PRECISION NOT NULL,
            closing_cost_base DOUBLE PRECISION NOT NULL,
            realized_net_pnl DOUBLE PRECISION NOT NULL,
            currency TEXT NOT NULL,
            reconciled_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE(pilot_key, closing_external_reference)
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS pg_v2_autotrader_equity_reconciliation_time_idx
        ON pg_v2_autotrader_equity_reconciliations(pilot_key, reconciled_at DESC)
        """,
    )
    with connect() as db:
        for statement in statements:
            db.execute(statement)
