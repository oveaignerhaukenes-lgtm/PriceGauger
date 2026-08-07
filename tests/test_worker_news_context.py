from analysis_status import AnalysisStatusStore
from news_context_engine import NewsContextAssessment, NewsWindow
from news_context_store import NewsContextStore
from telegram_query_builder import TelegramSearchPlan
import worker


NOW = "2026-08-07T20:00:00+00:00"


def _plan() -> TelegramSearchPlan:
    return TelegramSearchPlan(
        message_id="1",
        message_url="https://t.me/example/1",
        message_text="Material escalation update",
        event_type="event",
        target="unspecified",
        country="",
        domain="",
        search="event context",
        signal_score=2,
        published_at=NOW,
    )


def _context() -> NewsContextAssessment:
    return NewsContextAssessment(
        as_of=NOW,
        engine_version="news-context-v1",
        source_channel="example",
        source_post_count=1,
        coverage_start=NOW,
        coverage_end=NOW,
        coverage_warning="",
        conflict_level=0.8,
        fear_level=0.7,
        escalation_direction="escalating",
        physical_supply_risk=0.6,
        narrative_saturation=0.4,
        confirmation_quality=0.75,
        regime_label="elevated escalation",
        active_drivers=("shipping risk",),
        counter_signals=(),
        unresolved_questions=(),
        summary="Elevated context.",
        confidence=0.7,
        model="test-model",
        windows=(NewsWindow(1, 1, NOW, NOW, ("update",)),),
    )


def test_worker_persists_successful_news_context(tmp_path, monkeypatch):
    db_path = tmp_path / "worker.sqlite3"
    monkeypatch.setattr(worker, "openai_api_key", lambda: "test-key")

    class Engine:
        def __init__(self, **kwargs):
            pass

        def assess(self, plans, *, channel):
            assert list(plans) == [_plan()]
            assert channel == "example"
            return _context()

    monkeypatch.setattr(worker, "OpenAINewsContextEngine", Engine)

    result = worker._refresh_news_context(db_path=db_path, channel="example", plans=[_plan()])

    assert result == _context()
    assert NewsContextStore(db_path).load_latest() == _context()
    status = {item.step_key: item for item in AnalysisStatusStore(db_path).load()}
    assert status["context_state"].status == "COMPLETE"


def test_worker_keeps_last_valid_context_when_refresh_fails(tmp_path, monkeypatch):
    db_path = tmp_path / "worker.sqlite3"
    store = NewsContextStore(db_path)
    store.save(_context())
    monkeypatch.setattr(worker, "openai_api_key", lambda: "test-key")
    monkeypatch.setattr(store.__class__, "should_refresh", lambda self, plans: True)

    class FailingEngine:
        def __init__(self, **kwargs):
            pass

        def assess(self, plans, *, channel):
            raise RuntimeError("provider unavailable")

    monkeypatch.setattr(worker, "OpenAINewsContextEngine", FailingEngine)

    result = worker._refresh_news_context(db_path=db_path, channel="example", plans=[_plan()])

    assert result == _context()
    assert NewsContextStore(db_path).load_latest() == _context()
    status = {item.step_key: item for item in AnalysisStatusStore(db_path).load()}
    assert status["context_state"].status == "FAILED"
    assert "siste gyldige kontekst beholdes" in status["context_state"].detail
