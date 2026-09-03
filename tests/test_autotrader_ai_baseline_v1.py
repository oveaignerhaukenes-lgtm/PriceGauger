from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from autotrader_ai_baseline_v1 import (
    AIBaselineDecisionV1,
    STRATEGY_KEY,
    _decision_schema,
    _system_prompt,
    ai_decision_is_fresh_v1,
)
from autotrader_strategy_catalog_v2 import (
    AI_BASELINE_STRATEGY_V2,
    AUTOTRADER_STRATEGIES_V2,
)


def _decision(at: datetime) -> AIBaselineDecisionV1:
    return AIBaselineDecisionV1(
        instrument_id=11,
        market_name="US Tech 100",
        action_at=at,
        price=29_500.0,
        target_direction="LONG",
        confidence=0.61,
        horizon_minutes=30,
        summary="test",
        technical_case="test",
        news_case="test",
        invalidation="test",
        model="gpt-5-mini",
        context_hash="abc",
    )


def test_ai_baseline_uses_exact_three_state_structured_target():
    schema = _decision_schema()
    assert schema["properties"]["target_direction"]["enum"] == ["LONG", "SHORT", "FLAT"]
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {
        "target_direction", "confidence", "horizon_minutes", "summary",
        "technical_case", "news_case", "invalidation",
    }


def test_ai_baseline_prompt_explicitly_denies_sizing_and_execution_authority():
    prompt = _system_prompt()
    assert "no authority over position size" in prompt
    assert "leverage" in prompt
    assert "execution" in prompt
    assert "FLAT is a valid active decision" in prompt


def test_ai_decision_freshness_is_bounded():
    now = datetime(2026, 9, 3, 20, 0, tzinfo=timezone.utc)
    assert ai_decision_is_fresh_v1(_decision(now - timedelta(minutes=10)), now=now)
    assert not ai_decision_is_fresh_v1(_decision(now - timedelta(minutes=13)), now=now)


def test_ai_baseline_is_live_selectable_but_has_no_direct_order_path():
    assert STRATEGY_KEY == AI_BASELINE_STRATEGY_V2
    keys = {item.key for item in AUTOTRADER_STRATEGIES_V2}
    assert AI_BASELINE_STRATEGY_V2 in keys

    signal_source = Path("autotrader_ai_baseline_v1.py").read_text(encoding="utf-8")
    live_source = Path("autotrader_ai_live_runtime_v1.py").read_text(encoding="utf-8")
    assert "place_order(" not in signal_source
    assert "place_order(" not in live_source
    assert "trade/v2/orders" not in signal_source
    assert "trade/v2/orders" not in live_source
    assert "_persist_intent_and_request_v2" in live_source


def test_worker_collects_ai_shadow_and_dispatch_can_consume_it_live():
    worker_source = Path("worker.py").read_text(encoding="utf-8")
    dispatch_source = Path("autotrader_automanage_dispatch_v2.py").read_text(encoding="utf-8")
    comparison_source = Path("autotrader_pnl_comparison_v2.py").read_text(encoding="utf-8")

    assert "run_ai_baseline_shadow_once_v1" in worker_source
    assert "run_ai_live_strategy_once_v1" in dispatch_source
    assert "AI_BASELINE_STRATEGY_V2" in dispatch_source
    assert "load_ai_baseline_series_v1" in comparison_source
