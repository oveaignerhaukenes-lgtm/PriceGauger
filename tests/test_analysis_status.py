from analysis_status import AnalysisStatusStore, STEP_ORDER


def test_analysis_status_defaults_and_round_trip(tmp_path):
    store = AnalysisStatusStore(tmp_path / "status.sqlite3")

    initial = store.load()
    assert tuple(item.step_key for item in initial) == STEP_ORDER
    assert all(item.status == "PENDING" for item in initial)

    store.running("telegram_scoring", "Scorer poster")
    store.complete("semantic_filter", "9 godkjent; 1 filtrert")
    store.failed("decision_state", "testfeil")

    loaded = {item.step_key: item for item in store.load()}
    assert loaded["telegram_scoring"].status == "RUNNING"
    assert loaded["semantic_filter"].status == "COMPLETE"
    assert "1 filtrert" in loaded["semantic_filter"].detail
    assert loaded["decision_state"].status == "FAILED"


def test_begin_cycle_preserves_explicit_pending_components(tmp_path):
    store = AnalysisStatusStore(tmp_path / "status.sqlite3")
    store.complete("decision_state", "ferdig")

    store.begin_cycle()

    loaded = {item.step_key: item for item in store.load()}
    assert loaded["decision_state"].status == "PENDING"
    assert loaded["technical_state"].status == "PENDING"
    assert "Venter på workeren" in loaded["technical_state"].detail
    assert "Ikke koblet" in loaded["context_state"].detail


def test_unknown_step_and_status_are_rejected(tmp_path):
    store = AnalysisStatusStore(tmp_path / "status.sqlite3")

    try:
        store.set("unknown", "COMPLETE")
        assert False, "unknown step should fail"
    except ValueError:
        pass

    try:
        store.set("telegram_fetch", "MAYBE")
        assert False, "unknown status should fail"
    except ValueError:
        pass
