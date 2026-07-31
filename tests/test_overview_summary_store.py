from overview_ai_summary import build_overview_summary
from overview_service import OverviewData
from overview_summary_contract import OverviewSummary
from overview_summary_store import OverviewSummaryStore


def _summary(headline: str = "Persisted summary") -> OverviewSummary:
    return OverviewSummary(
        regime="ACTIVE_WAR",
        sensitivity="HEADLINE_SENSITIVE",
        headline=headline,
        summary="Stored worker-generated market context.",
        key_driver="Shipping risk.",
        caveat="Technical confirmation pending.",
        model="test-model",
    )


def test_summary_round_trip(tmp_path):
    path = tmp_path / "overview.sqlite3"
    store = OverviewSummaryStore(path)
    store.save(
        information_snapshot_id="information-state:1",
        as_of="2026-07-31T12:00:00+00:00",
        summary=_summary(),
    )

    loaded = store.load_latest()

    assert loaded is not None
    assert loaded.headline == "Persisted summary"
    assert loaded.model == "test-model"


def test_ui_prefers_persisted_summary_without_model_call():
    persisted = _summary("Worker-owned summary")
    data = OverviewData(
        flow=None,
        markets=(),
        latest_posts=(),
        information_state=None,
        latest_alert=None,
        summary=persisted,
    )

    result = build_overview_summary(data, api_key="would-call-model")

    assert result is persisted
    assert result.headline == "Worker-owned summary"
