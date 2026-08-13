from pathlib import Path


SCHEMA = Path(__file__).resolve().parents[1] / "db_v2_schema.sql"


def _schema_text() -> str:
    return SCHEMA.read_text(encoding="utf-8")


def test_db_v2_schema_declares_core_tables() -> None:
    schema = _schema_text()
    for table in (
        "pg_v2_markets",
        "pg_v2_instruments",
        "pg_v2_instrument_sources",
        "pg_v2_collection_subscriptions",
        "pg_v2_market_bars_1m",
        "pg_v2_technical_recipes",
        "pg_v2_technical_states",
        "pg_v2_analysis_recipes",
        "pg_v2_forecasts",
        "pg_v2_forecast_layer_outputs",
        "pg_v2_forecast_outcomes",
        "pg_v2_context_theses",
        "pg_v2_context_thesis_updates",
        "pg_v2_raw_evidence",
        "pg_v2_context_evidence_links",
        "pg_v2_ai_decisions",
        "pg_v2_risk_policies",
        "pg_v2_strategy_recipes",
        "pg_v2_runtime_status",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in schema


def test_market_bars_are_compact_and_provider_agnostic() -> None:
    schema = _schema_text()
    start = schema.index("CREATE TABLE IF NOT EXISTS pg_v2_market_bars_1m")
    end = schema.index("CREATE TABLE IF NOT EXISTS pg_v2_technical_recipes")
    bars = schema[start:end]

    assert "instrument_id" in bars
    assert "bar_time" in bars
    assert "open DOUBLE PRECISION" in bars
    assert "high DOUBLE PRECISION" in bars
    assert "low DOUBLE PRECISION" in bars
    assert "close DOUBLE PRECISION" in bars
    assert "provider" not in bars
    assert "uic" not in bars.lower()
    assert "JSONB" not in bars


def test_instrument_identity_is_provider_mapping_not_market_bar_metadata() -> None:
    schema = _schema_text()
    assert "provider_instrument_id TEXT NOT NULL" in schema
    assert "price_multiplier NUMERIC" in schema
    assert "CREATE TABLE IF NOT EXISTS pg_v2_collection_subscriptions" in schema


def test_forecast_layers_are_cacheable_and_recipe_identified() -> None:
    schema = _schema_text()
    assert "input_fingerprint TEXT NOT NULL" in schema
    assert "analysis_recipe_id UUID" in schema
    assert "UNIQUE(market_id, as_of, layer_name, layer_version, input_fingerprint)" in schema


def test_ai_decisions_store_structured_and_human_readable_forms() -> None:
    schema = _schema_text()
    assert "structured_decision_json JSONB" in schema
    assert "human_summary TEXT NOT NULL" in schema
    assert "'HOLD', 'ENTER', 'REDUCE', 'EXIT', 'MODIFY_RISK'" in schema


def test_risk_policy_defaults_to_sim_only() -> None:
    schema = _schema_text()
    assert "sim_only BOOLEAN NOT NULL DEFAULT TRUE" in schema
