"""No unsolicited LLM traffic; explicit operator AI options remain independent."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

import autotrader_v3_ai_manager_shadow_v1 as shadow
import worker
from background_ai_policy_v1 import background_ai_enabled_v1
from news_context_store import NewsContextStore
from telegram_flow_store import TelegramFlowStore
from telegram_query_builder import build_search_plan


def _post():
    return build_search_plan(
        message_id="15", message_url="https://t.me/example/15",
        text="Oil terminal outage in the Gulf", published_at="2026-11-15T10:00:00+00:00",
    )


def test_background_ai_requires_explicit_environment_opt_in(monkeypatch):
    monkeypatch.delenv("PRICEGAUGER_BACKGROUND_AI_ENABLED", raising=False)
    assert background_ai_enabled_v1() is False
    for value in ("0", "false", "off", "garbage"):
        monkeypatch.setenv("PRICEGAUGER_BACKGROUND_AI_ENABLED", value)
        assert background_ai_enabled_v1() is False
    monkeypatch.setenv("PRICEGAUGER_BACKGROUND_AI_ENABLED", "1")
    assert background_ai_enabled_v1() is True


def test_telegram_raw_data_is_persisted_without_any_llm_request(tmp_path, monkeypatch):
    monkeypatch.delenv("PRICEGAUGER_BACKGROUND_AI_ENABLED", raising=False)
    monkeypatch.setattr(worker, "openai_api_key", lambda: "configured-but-unavailable")
    monkeypatch.setattr(worker, "OpenAITelegramFlowScorer",
                        lambda **kwargs: pytest.fail("background scorer must not start"))
    monkeypatch.setattr(worker, "OpenAINewsContextEngine",
                        lambda **kwargs: pytest.fail("background context must not start"))
    db_path = tmp_path / "raw.db"
    original = _post()
    manual_indicator_calls = []
    monkeypatch.setattr(worker, "refresh_indicator_ai_once_v1",
                        lambda **kwargs: manual_indicator_calls.append(kwargs) or 0)
    worker.run_once(db_path=db_path, plans_fetcher=lambda *a, **k: [original])
    assert len(manual_indicator_calls) == 1  # persisted user opt-in still checked
    with TelegramFlowStore(db_path)._connect() as db:
        rows = db.execute("SELECT message_id,channel,payload_json FROM telegram_raw_posts").fetchall()
    assert len(rows) == 1
    assert rows[0]["message_id"] == "15"
    assert 'Oil terminal outage' in rows[0]["payload_json"]
    assert NewsContextStore(db_path).load_latest() is None
    assert worker._refresh_news_context(
        db_path=db_path, channel="example", plans=[original],
    ) is None
    worker.run_once(db_path=db_path, plans_fetcher=lambda *a, **k: [original])
    with TelegramFlowStore(db_path)._connect() as db:
        assert db.execute("SELECT COUNT(*) FROM telegram_raw_posts").fetchone()[0] == 1


def test_shadow_reviews_are_manual_opt_in_or_live_modifier(tmp_path, monkeypatch):
    db = str(tmp_path / "shadow.db")
    monkeypatch.setattr(shadow, "load_autotrader_config_v3",
                        lambda *a, **k: SimpleNamespace(modifiers=()))
    assert shadow.shadow_settings_v1("instance", db_path=db)["enabled"] is False
    monkeypatch.setattr(shadow, "load_autotrader_config_v3",
                        lambda *a, **k: SimpleNamespace(modifiers=("ai-loss-manager",)))
    assert shadow.shadow_settings_v1("instance", db_path=db)["enabled"] is True
    shadow.save_shadow_settings_v1(instance_id="instance", enabled=False,
                                   trigger_seconds=45, db_path=db)
    assert shadow.shadow_settings_v1("instance", db_path=db) == {
        "enabled": False, "trigger_seconds": 45,
    }
