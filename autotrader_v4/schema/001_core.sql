-- AutoTrader V4: ISOLATED, EMPTY Postgres database (not a Railway migration).
-- Reviewed SQL spec; DO NOT execute against current V3 production database.
-- Configure distinct PostgreSQL database credentials for V4, with explicit migrations.

BEGIN;
CREATE SCHEMA IF NOT EXISTS at4;

CREATE TABLE IF NOT EXISTS at4.accounts (
    account_id TEXT PRIMARY KEY,
    currency CHAR(3) NOT NULL CHECK (currency = upper(currency)),
    display_label TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS at4.instruments (
    uic BIGINT NOT NULL CHECK (uic > 0),
    asset_type TEXT NOT NULL CHECK (length(asset_type) > 0),
    symbol TEXT,
    PRIMARY KEY (uic, asset_type)
);

CREATE TABLE IF NOT EXISTS at4.strategy_assignment_events (
    event_id UUID PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES at4.accounts(account_id),
    instance_id UUID NOT NULL,
    uic BIGINT NOT NULL,
    asset_type TEXT NOT NULL,
    strategy_key TEXT NOT NULL,
    strategy_version TEXT NOT NULL,
    config_digest TEXT NOT NULL,
    config_json JSONB NOT NULL,
    armed BOOLEAN NOT NULL DEFAULT FALSE,
    observed_at TIMESTAMPTZ NOT NULL,
    effective_at TIMESTAMPTZ NOT NULL,
    source_event_key TEXT NOT NULL UNIQUE,
    FOREIGN KEY (uic, asset_type) REFERENCES at4.instruments(uic, asset_type)
);
CREATE INDEX IF NOT EXISTS at4_assignment_by_account_time
    ON at4.strategy_assignment_events(account_id, effective_at DESC);

CREATE TABLE IF NOT EXISTS at4.closed_bars_1m (
    uic BIGINT NOT NULL,
    asset_type TEXT NOT NULL,
    bar_time TIMESTAMPTZ NOT NULL,
    open NUMERIC(24,10) NOT NULL CHECK (open > 0),
    high NUMERIC(24,10) NOT NULL CHECK (high > 0),
    low NUMERIC(24,10) NOT NULL CHECK (low > 0),
    close NUMERIC(24,10) NOT NULL CHECK (close > 0),
    volume NUMERIC(24,10),
    source_at TIMESTAMPTZ,
    quality TEXT NOT NULL DEFAULT 'UNKNOWN',
    PRIMARY KEY (uic, asset_type, bar_time),
    FOREIGN KEY (uic, asset_type) REFERENCES at4.instruments(uic, asset_type),
    CHECK (high >= low AND high >= greatest(open, close)
           AND low <= least(open, close))
);

CREATE TABLE IF NOT EXISTS at4.strategy_decisions (
    decision_key TEXT PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES at4.accounts(account_id),
    instance_id UUID NOT NULL,
    uic BIGINT NOT NULL,
    asset_type TEXT NOT NULL,
    strategy_key TEXT NOT NULL,
    strategy_version TEXT NOT NULL,
    config_digest TEXT NOT NULL,
    decided_at TIMESTAMPTZ NOT NULL,
    evidence_cutoff TIMESTAMPTZ NOT NULL,
    bid NUMERIC(24,10),
    ask NUMERIC(24,10),
    provider_at TIMESTAMPTZ,
    desired_signed_units NUMERIC(24,10) NOT NULL,
    reason TEXT NOT NULL,
    FOREIGN KEY (uic, asset_type) REFERENCES at4.instruments(uic, asset_type),
    CHECK (evidence_cutoff <= decided_at),
    CHECK (bid IS NULL OR bid > 0),
    CHECK (ask IS NULL OR ask > 0),
    CHECK (bid IS NULL OR ask IS NULL OR bid <= ask)
);
CREATE INDEX IF NOT EXISTS at4_decisions_by_instance
    ON at4.strategy_decisions(instance_id, decided_at DESC);

CREATE TABLE IF NOT EXISTS at4.order_intents (
    intent_key TEXT PRIMARY KEY,
    decision_key TEXT NOT NULL REFERENCES at4.strategy_decisions(decision_key),
    account_id TEXT NOT NULL REFERENCES at4.accounts(account_id),
    uic BIGINT NOT NULL,
    asset_type TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN
        ('RESERVED','SUBMITTING','SUBMITTED','UNKNOWN','RECONCILED','REJECTED')),
    side TEXT NOT NULL CHECK (side IN ('Buy','Sell')),
    requested_units NUMERIC(24,10) NOT NULL CHECK (requested_units > 0),
    broker_order_id TEXT,
    requested_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    last_error_category TEXT,
    FOREIGN KEY (uic, asset_type) REFERENCES at4.instruments(uic, asset_type),
    UNIQUE (account_id, intent_key)
);
-- Persistent single unresolved broker boundary. SQL-level safety is necessary
-- even when two Python processes are mistakenly started.
CREATE UNIQUE INDEX IF NOT EXISTS at4_one_unresolved_intent_per_boundary
    ON at4.order_intents(account_id, uic, asset_type)
    WHERE state IN ('RESERVED','SUBMITTING','SUBMITTED','UNKNOWN');

CREATE TABLE IF NOT EXISTS at4.broker_order_events (
    event_key TEXT PRIMARY KEY,
    intent_key TEXT NOT NULL REFERENCES at4.order_intents(intent_key),
    event_at TIMESTAMPTZ NOT NULL,
    broker_order_id TEXT,
    old_state TEXT,
    new_state TEXT NOT NULL,
    broker_evidence_key TEXT,
    detail_category TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS at4_order_history_by_intent
    ON at4.broker_order_events(intent_key, event_at);

CREATE TABLE IF NOT EXISTS at4.broker_fills (
    account_id TEXT NOT NULL REFERENCES at4.accounts(account_id),
    broker_fill_id TEXT NOT NULL,
    broker_order_id TEXT,
    uic BIGINT NOT NULL,
    asset_type TEXT NOT NULL,
    filled_at TIMESTAMPTZ NOT NULL,
    side TEXT NOT NULL CHECK (side IN ('Buy','Sell')),
    units NUMERIC(24,10) NOT NULL CHECK (units > 0),
    price NUMERIC(24,10) NOT NULL CHECK (price > 0),
    position_id TEXT,
    owner_decision_key TEXT REFERENCES at4.strategy_decisions(decision_key),
    is_manual BOOLEAN,
    PRIMARY KEY (account_id, broker_fill_id),
    FOREIGN KEY (uic, asset_type) REFERENCES at4.instruments(uic, asset_type)
);
CREATE INDEX IF NOT EXISTS at4_fills_by_account_at
    ON at4.broker_fills(account_id, filled_at DESC);

CREATE TABLE IF NOT EXISTS at4.account_snapshots (
    account_id TEXT NOT NULL REFERENCES at4.accounts(account_id),
    observed_at TIMESTAMPTZ NOT NULL,
    currency CHAR(3) NOT NULL,
    total_value NUMERIC(24,8),
    cash_balance NUMERIC(24,8),
    margin_used NUMERIC(24,8),
    reliability TEXT NOT NULL,
    source TEXT NOT NULL,
    PRIMARY KEY (account_id, observed_at)
);

CREATE TABLE IF NOT EXISTS at4.broker_transactions (
    account_id TEXT NOT NULL REFERENCES at4.accounts(account_id),
    transaction_id TEXT NOT NULL,
    booked_at TIMESTAMPTZ NOT NULL,
    kind TEXT NOT NULL,
    amount NUMERIC(24,8) NOT NULL,
    currency CHAR(3) NOT NULL,
    broker_order_id TEXT,
    source_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (account_id, transaction_id)
);
CREATE INDEX IF NOT EXISTS at4_transactions_by_account_at
    ON at4.broker_transactions(account_id, booked_at DESC);

CREATE TABLE IF NOT EXISTS at4.official_daily_performance (
    account_id TEXT NOT NULL REFERENCES at4.accounts(account_id),
    value_date DATE NOT NULL,
    currency CHAR(3) NOT NULL,
    broker_account_value NUMERIC(24,8),
    broker_profit_loss NUMERIC(24,8),
    time_weighted_fraction NUMERIC(24,12),
    reliability TEXT NOT NULL DEFAULT 'UNVERIFIED',
    PRIMARY KEY (account_id, value_date)
);

-- Deliberately no context/news/AI tables, no tick-firehose table, no
-- AUTO-LIVE launch functions or direct broker order-submit credentials.
COMMIT;
