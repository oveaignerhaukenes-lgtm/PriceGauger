from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import indicator_ai_insights_v1 as insights
from trading_desk import ChartBar


def test_indicator_ai_returns_before_any_work_without_api_key(monkeypatch):
    monkeypatch.setattr(
        insights,
        "load_ui_workspace_state_v2",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("UI state should not be read")),
    )
    assert insights.refresh_indicator_ai_once_v1(api_key="") == 0


def test_indicator_ai_off_state_never_reaches_provider(monkeypatch):
    monkeypatch.setattr(
        insights,
        "load_ui_workspace_state_v2",
        lambda *_args, **_kwargs: SimpleNamespace(state={"indicator_ai_enabled": False}),
    )
    monkeypatch.setattr(
        insights,
        "_request_assessments",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("provider must remain off")),
    )
    assert insights.refresh_indicator_ai_once_v1(api_key="configured") == 0


def test_indicator_ai_schema_requires_exact_selected_indicators():
    schema = insights._output_schema(["MACD", "RSI"])
    assessments = schema["properties"]["assessments"]
    assert assessments["additionalProperties"] is False
    assert assessments["required"] == ["MACD", "RSI"]
    assert set(assessments["properties"]) == {"MACD", "RSI"}
    assert assessments["properties"]["MACD"]["maxLength"] == 150


def test_indicator_ai_identity_is_order_independent():
    assert insights._indicator_set_key(["MACD", "RSI"]) == insights._indicator_set_key(["RSI", "MACD"])


def _bar(stamp: datetime, value: float) -> ChartBar:
    return ChartBar(
        market="Gold",
        bar_time=stamp.isoformat(),
        open=value,
        high=value,
        low=value,
        close=value,
        volume=None,
    )


def test_indicator_ai_uses_only_complete_resampled_buckets():
    start = datetime(2026, 9, 7, 0, 0, tzinfo=timezone.utc)
    raw = [_bar(start + timedelta(minutes=index), 100.0 + index) for index in range(7)]

    bars = insights._closed_resampled_bars(raw, timeframe="5m")

    assert len(bars) == 1
    assert bars[0].bar_time == start.isoformat()
    assert bars[0].close == 104.0


def test_indicator_ai_payload_normalizes_chartbar_string_timestamp():
    stamp = datetime(2026, 9, 7, 0, 0, tzinfo=timezone.utc)
    workspace = SimpleNamespace(
        technical_state=SimpleNamespace(
            trend_state="UP",
            momentum_state="RISING",
            volatility_state="NORMAL",
            structure_state="BULLISH",
            score=0.4,
            confidence=0.7,
        )
    )
    technical = SimpleNamespace()
    monkey_close = _bar(stamp, 100.0)

    # No indicators means the payload path can be tested without constructing a full TechnicalIndicators object.
    payload = insights._source_payload(
        market="Gold",
        timeframe="5m",
        bars=(monkey_close,),
        technical=technical,
        workspace=workspace,
        indicator_names=(),
    )

    assert payload["source_bar_time"] == stamp.isoformat()


def test_indicator_ai_is_worker_owned_and_ui_reader_stays_provider_free():
    worker = open("worker.py", encoding="utf-8").read()
    guide = open("indicator_guide_v1.py", encoding="utf-8").read().lower()
    page = open("pages/0_TradingDesk.py", encoding="utf-8").read().lower()

    assert "refresh_indicator_ai_once_v1" in worker
    assert "indicator AI refresh failed; worker continues" in worker
    assert "load_latest_indicator_ai_v1" in guide
    assert "requests." not in guide
    assert "openai" not in page


def test_indicator_ai_opt_in_is_safe_workspace_preference_only():
    import tradingdesk_workspace_state_v2 as workspace

    assert workspace._SAFE_SESSION_KEYS["indicator_ai_enabled"] == workspace.INDICATOR_AI_SESSION_KEY
    assert workspace.INDICATOR_AI_SESSION_KEY == "tradingdesk-indicator-ai-enabled"
    for forbidden in ("live_open_armed", "entry_mode", "approval_request_id", "strategy_activation"):
        assert forbidden not in workspace._SAFE_SESSION_KEYS
