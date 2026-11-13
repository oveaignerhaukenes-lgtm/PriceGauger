"""V4 is an isolated no-authority prototype; preserve the existing LIVE service."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from autotrader_v4 import (
    BboObservation, IntentState, SaxoBoundary, StrategyRef, TradeDecision,
    advance_intent_state,
)


NOW = datetime(2026, 10, 21, 18, 0, tzinfo=timezone.utc)


def boundary():
    return SaxoBoundary(account_id="ACCOUNT_TEST", uic=4912, asset_type="CfdOnIndex")


def strategy():
    return StrategyRef("macd5", "v1", "sha256-test")


def test_exact_broker_boundary_is_required():
    assert boundary().uic == 4912
    for kwargs in (
        {"account_id": ""}, {"uic": 0}, {"asset_type": ""}
    ):
        args = dict(account_id="ACCOUNT_TEST", uic=4912, asset_type="CfdOnIndex")
        args.update(kwargs)
        with pytest.raises(ValueError):
            SaxoBoundary(**args)


def test_strategy_has_immutable_version_and_digest():
    assert strategy().version == "v1"
    with pytest.raises(ValueError):
        StrategyRef("macd5", "", "anything")


def test_quote_validation_is_strict_and_missing_provider_clock_is_not_live():
    clean = BboObservation(boundary(), NOW, "25000.50", "25001.00", NOW)
    assert clean.is_fresh(now=NOW + timedelta(seconds=1), max_age_seconds=3)
    assert not clean.is_fresh(now=NOW + timedelta(seconds=4), max_age_seconds=3)
    assert not clean.is_fresh(now=NOW - timedelta(seconds=1), max_age_seconds=3)
    assert not BboObservation(boundary(), NOW, "25000", "25001").is_fresh(
        now=NOW, max_age_seconds=3
    )
    with pytest.raises(ValueError):
        BboObservation(boundary(), NOW, "5", "4", NOW)
    with pytest.raises(TypeError):
        BboObservation(boundary(), NOW, 1.2, 1.3, NOW)


def test_decision_rejects_lookahead_and_binary_float_sizing():
    decision = TradeDecision(boundary(), strategy(), NOW, NOW - timedelta(seconds=1),
                             "0.01", "test-decision-1")
    assert decision.desired_signed_units == Decimal("0.01")
    with pytest.raises(ValueError):
        TradeDecision(boundary(), strategy(), NOW, NOW + timedelta(seconds=1),
                      "0.01", "test-decision-2")
    with pytest.raises(TypeError):
        TradeDecision(boundary(), strategy(), NOW, NOW, 0.01, "test-decision-3")
    with pytest.raises(ValueError):
        TradeDecision(boundary(), strategy(), NOW.replace(tzinfo=None), NOW,
                      "0.01", "test-decision-4")


def test_unknown_order_cannot_be_retry_or_resolved_without_broker_truth():
    assert advance_intent_state(IntentState.RESERVED, IntentState.SUBMITTING) == IntentState.SUBMITTING
    assert advance_intent_state(IntentState.SUBMITTING, IntentState.UNKNOWN) == IntentState.UNKNOWN
    with pytest.raises(ValueError):
        advance_intent_state(IntentState.UNKNOWN, IntentState.RESERVED)
    with pytest.raises(ValueError):
        advance_intent_state(IntentState.UNKNOWN, IntentState.REJECTED)
    with pytest.raises(ValueError):
        advance_intent_state(IntentState.UNKNOWN, IntentState.RECONCILED)
    with pytest.raises(ValueError):
        advance_intent_state(IntentState.UNKNOWN, IntentState.REJECTED, broker_evidence=True)
    assert advance_intent_state(
        IntentState.UNKNOWN, IntentState.RECONCILED, broker_evidence=True
    ) == IntentState.RECONCILED
    assert advance_intent_state(
        IntentState.UNKNOWN, IntentState.REJECTED, broker_evidence=True,
        definitive_rejection=True,
    ) == IntentState.REJECTED


def test_terminal_order_states_cannot_be_reused():
    for state in (IntentState.RECONCILED, IntentState.REJECTED):
        for target in IntentState:
            with pytest.raises(ValueError):
                advance_intent_state(state, target, broker_evidence=True, definitive_rejection=True)


def test_prototype_has_no_live_runtime_import_or_order_post():
    root = Path("autotrader_v4")
    package = (root / "domain.py").read_text(encoding="utf-8")
    init = (root / "__init__.py").read_text(encoding="utf-8")
    for source in (package, init):
        assert "saxo_trading" not in source
        assert "autotrader_v3_live_runtime" not in source
        assert "place_order" not in source
        assert "requests.post" not in source
    ddl = (root / "schema" / "001_core.sql").read_text(encoding="utf-8")
    assert "at4_one_unresolved_intent_per_boundary" in ddl
    assert "CREATE SCHEMA IF NOT EXISTS at4;" in ddl
    assert "pg_v2_market_bars_1m" not in ddl
