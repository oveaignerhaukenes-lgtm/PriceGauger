from __future__ import annotations

from types import SimpleNamespace

import indicator_ai_insights_v1 as insights


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
    source = open("tradingdesk_workspace_state_v2.py", encoding="utf-8").read()
    assert '"indicator_ai_enabled": INDICATOR_AI_SESSION_KEY' in source
    assert 'INDICATOR_AI_SESSION_KEY = "tradingdesk-indicator-ai-enabled"' in source
    assert '"indicator_ai_enabled"' in source
    assert "execution" not in source.lower().split("_SAFE_SESSION_KEYS", 1)[1].split("}", 1)[0]
