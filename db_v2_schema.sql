-- PriceGauger DB v2 foundation schema
-- PostgreSQL only. Independent of legacy v1 tables.

CREATE TABLE IF NOT EXISTS pg_v2_markets (
    market_id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    category TEXT NOT NULL,
    base_currency TEXT,
    quote_currency TEXT,
    canonical_unit TEXT,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS pg_v2_instruments (
    instrument_id BIGSERIAL PRIMARY KEY,
    market_id BIGINT NOT NULL REFERENCES pg_v2_markets(market_id),
    instrument_type TEXT NOT NULL,
    display_name TEXT NOT NULL,
    valid_from TIMESTAMPTZ,
    valid_to TIMESTAMPTZ,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS pg_v2_instrument_sources (
    instrument_source_id BIGSERIAL PRIMARY KEY,
    instrument_id BIGINT NOT NULL REFERENCES pg_v2_instruments(instrument_id),
    provider TEXT NOT NULL,
    provider_instrument_id TEXT NOT NULL,
    asset_type TEXT,
    symbol TEXT,
    price_multiplier NUMERIC,
    metadata_json JSONB,
    valid_from TIMESTAMPTZ,
    valid_to TIMESTAMPTZ,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS pg_v2_instrument_source_identity_idx
    ON pg_v2_instrument_sources(provider, provider_instrument_id, COALESCE(valid_from, '-infinity'::timestamptz));

CREATE TABLE IF NOT EXISTS pg_v2_collection_subscriptions (
    instrument_id BIGINT PRIMARY KEY REFERENCES pg_v2_instruments(instrument_id),
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    resolution TEXT NOT NULL DEFAULT '1m',
    enabled_at TIMESTAMPTZ,
    disabled_at TIMESTAMPTZ,
    CHECK (resolution = '1m')
);

CREATE TABLE IF NOT EXISTS pg_v2_market_bars_1m (
    instrument_id BIGINT NOT NULL REFERENCES pg_v2_instruments(instrument_id),
    bar_time TIMESTAMPTZ NOT NULL,
    open DOUBLE PRECISION NOT NULL,
    high DOUBLE PRECISION NOT NULL,
    low DOUBLE PRECISION NOT NULL,
    close DOUBLE PRECISION NOT NULL,
    volume DOUBLE PRECISION,
    quality_flags INTEGER,
    PRIMARY KEY (instrument_id, bar_time),
    CHECK (high >= low),
    CHECK (high >= open AND high >= close),
    CHECK (low <= open AND low <= close)
);

CREATE TABLE IF NOT EXISTS pg_v2_technical_recipes (
    technical_recipe_id UUID PRIMARY KEY,
    name TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version > 0),
    parameters_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(name, version)
);

CREATE TABLE IF NOT EXISTS pg_v2_technical_states (
    technical_state_id UUID PRIMARY KEY,
    market_id BIGINT NOT NULL REFERENCES pg_v2_markets(market_id),
    as_of TIMESTAMPTZ NOT NULL,
    technical_recipe_id UUID NOT NULL REFERENCES pg_v2_technical_recipes(technical_recipe_id),
    trend_state TEXT,
    momentum_state TEXT,
    volatility_state TEXT,
    features_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(market_id, as_of, technical_recipe_id)
);

CREATE INDEX IF NOT EXISTS pg_v2_technical_states_market_time_idx
    ON pg_v2_technical_states(market_id, as_of DESC);

CREATE TABLE IF NOT EXISTS pg_v2_analysis_recipes (
    analysis_recipe_id UUID PRIMARY KEY,
    name TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version > 0),
    technical_recipe_id UUID NOT NULL REFERENCES pg_v2_technical_recipes(technical_recipe_id),
    enabled_layers_json JSONB NOT NULL,
    layer_versions_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(name, version)
);

CREATE TABLE IF NOT EXISTS pg_v2_forecasts (
    forecast_id UUID PRIMARY KEY,
    market_id BIGINT NOT NULL REFERENCES pg_v2_markets(market_id),
    as_of TIMESTAMPTZ NOT NULL,
    horizon_seconds INTEGER NOT NULL CHECK (horizon_seconds > 0),
    technical_state_id UUID NOT NULL REFERENCES pg_v2_technical_states(technical_state_id),
    analysis_recipe_id UUID NOT NULL REFERENCES pg_v2_analysis_recipes(analysis_recipe_id),
    baseline_return DOUBLE PRECISION,
    composed_return DOUBLE PRECISION,
    lower_return DOUBLE PRECISION,
    upper_return DOUBLE PRECISION,
    path_spec_json JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS pg_v2_forecasts_market_time_idx
    ON pg_v2_forecasts(market_id, as_of DESC, horizon_seconds);

CREATE TABLE IF NOT EXISTS pg_v2_forecast_layer_outputs (
    layer_output_id UUID PRIMARY KEY,
    market_id BIGINT NOT NULL REFERENCES pg_v2_markets(market_id),
    as_of TIMESTAMPTZ NOT NULL,
    layer_name TEXT NOT NULL,
    layer_version TEXT NOT NULL,
    input_fingerprint TEXT NOT NULL,
    directional_bias DOUBLE PRECISION,
    velocity_modifier DOUBLE PRECISION,
    uncertainty_modifier DOUBLE PRECISION,
    reversal_probability DOUBLE PRECISION CHECK (reversal_probability IS NULL OR reversal_probability BETWEEN 0 AND 1),
    squeeze_probability DOUBLE PRECISION CHECK (squeeze_probability IS NULL OR squeeze_probability BETWEEN 0 AND 1),
    regime_confidence DOUBLE PRECISION CHECK (regime_confidence IS NULL OR regime_confidence BETWEEN 0 AND 1),
    details_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(market_id, as_of, layer_name, layer_version, input_fingerprint)
);

CREATE TABLE IF NOT EXISTS pg_v2_forecast_outcomes (
    forecast_id UUID PRIMARY KEY REFERENCES pg_v2_forecasts(forecast_id),
    matured_at TIMESTAMPTZ NOT NULL,
    realized_terminal_price DOUBLE PRECISION,
    realized_return DOUBLE PRECISION,
    absolute_error DOUBLE PRECISION,
    signed_error DOUBLE PRECISION,
    status TEXT NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS pg_v2_context_theses (
    context_thesis_id UUID PRIMARY KEY,
    market_id BIGINT REFERENCES pg_v2_markets(market_id),
    as_of TIMESTAMPTZ NOT NULL,
    thesis_type TEXT NOT NULL,
    claim TEXT NOT NULL,
    directional_or_risk_implication TEXT NOT NULL,
    evidence_summary TEXT NOT NULL,
    strengtheners TEXT,
    invalidators TEXT,
    missing_information TEXT,
    structured_claim_json JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS pg_v2_context_thesis_updates (
    context_update_id UUID PRIMARY KEY,
    context_thesis_id UUID NOT NULL REFERENCES pg_v2_context_theses(context_thesis_id),
    as_of TIMESTAMPTZ NOT NULL,
    update_type TEXT NOT NULL,
    summary TEXT NOT NULL,
    structured_update_json JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS pg_v2_raw_evidence (
    evidence_id UUID PRIMARY KEY,
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    published_at TIMESTAMPTZ,
    observed_at TIMESTAMPTZ NOT NULL,
    content_text TEXT,
    content_hash TEXT NOT NULL,
    metadata_json JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(source_type, source_id, content_hash)
);

CREATE TABLE IF NOT EXISTS pg_v2_context_evidence_links (
    context_thesis_id UUID NOT NULL REFERENCES pg_v2_context_theses(context_thesis_id),
    evidence_id UUID NOT NULL REFERENCES pg_v2_raw_evidence(evidence_id),
    PRIMARY KEY (context_thesis_id, evidence_id)
);

CREATE TABLE IF NOT EXISTS pg_v2_ai_decisions (
    ai_decision_id UUID PRIMARY KEY,
    market_id BIGINT REFERENCES pg_v2_markets(market_id),
    as_of TIMESTAMPTZ NOT NULL,
    analysis_recipe_id UUID NOT NULL REFERENCES pg_v2_analysis_recipes(analysis_recipe_id),
    forecast_id UUID REFERENCES pg_v2_forecasts(forecast_id),
    action TEXT NOT NULL CHECK (action IN ('HOLD', 'ENTER', 'REDUCE', 'EXIT', 'MODIFY_RISK')),
    direction TEXT CHECK (direction IS NULL OR direction IN ('LONG', 'SHORT', 'FLAT')),
    confidence DOUBLE PRECISION CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1),
    technical_basis TEXT NOT NULL,
    context_effect TEXT,
    invalidation TEXT,
    structured_decision_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    human_summary TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS pg_v2_risk_policies (
    risk_policy_id UUID PRIMARY KEY,
    name TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version > 0),
    max_trade_exposure NUMERIC,
    max_instrument_exposure NUMERIC,
    max_total_exposure NUMERIC,
    max_session_loss NUMERIC,
    require_stop_loss BOOLEAN NOT NULL DEFAULT TRUE,
    take_profit_required BOOLEAN NOT NULL DEFAULT FALSE,
    sim_only BOOLEAN NOT NULL DEFAULT TRUE,
    allowed_instruments_json JSONB,
    parameters_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(name, version)
);

CREATE TABLE IF NOT EXISTS pg_v2_strategy_recipes (
    strategy_recipe_id UUID PRIMARY KEY,
    name TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version > 0),
    analysis_recipe_id UUID NOT NULL REFERENCES pg_v2_analysis_recipes(analysis_recipe_id),
    risk_policy_id UUID NOT NULL REFERENCES pg_v2_risk_policies(risk_policy_id),
    rules_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(name, version)
);

CREATE TABLE IF NOT EXISTS pg_v2_runtime_status (
    service TEXT NOT NULL,
    stage TEXT NOT NULL,
    status TEXT NOT NULL,
    detail TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY(service, stage)
);
