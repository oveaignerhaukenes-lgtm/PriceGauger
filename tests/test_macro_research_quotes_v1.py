from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from macro_research_quotes_v1 import MacroResearchRecorder, research_rows, source_time_rows
from macro_release_lag_observer_v1 import study_release
from database import connect


def test_delayed_bbo_archived_on_source_clock_without_live_contamination(tmp_path):
    path = str(tmp_path / "archive.db")
    capture = MacroResearchRecorder(path)
    center = datetime(2026, 11, 25, 13, 30, tzinfo=timezone.utc)
    for second in (-2, -1, 0, 1, 2):
        source = center + timedelta(seconds=second)
        receipt = source + timedelta(minutes=10)
        price = 40.0 if second < 1 else 40.1
        q = SimpleNamespace(market="Silver", uic=42, asset_type="Cfd", bid=price, ask=price+.001)
        assert capture.observe(q, provider_at=source, received_at=receipt, delay=10)
        assert not capture.observe(q, provider_at=source, received_at=receipt, delay=10)
    rows = research_rows(center-timedelta(minutes=3), center+timedelta(minutes=15), db_path=path)
    assert len(rows) == 5
    assert rows[0]["delay_minutes"] == 10
    assert rows[0]["received_at"] != rows[0]["quote_at"]
    assert not study_release(rows, event=center)["markets"]
    report = study_release(source_time_rows(rows), event=center)
    assert report["markets"][0]["first_move"]["seconds"] == 1
    assert rows[0]["received_at"] != rows[0]["quote_at"]
    with connect(path) as db:
        assert db.execute("SELECT COUNT(*) AS n FROM macro_research_quotes_1s").fetchone()["n"] == 5


def test_rejects_unknown_source_clock_stale_and_tech100(tmp_path):
    capture = MacroResearchRecorder(str(tmp_path / "archive.db"))
    now = datetime(2026, 11, 25, tzinfo=timezone.utc)
    q = SimpleNamespace(market="Gold", uic=42, asset_type="Cfd", bid=100, ask=101)
    assert not capture.observe(q, provider_at=None, received_at=now, delay=10)
    assert not capture.observe(q, provider_at=now, received_at=now, delay=10)
    assert not capture.observe(q, provider_at=now-timedelta(minutes=20), received_at=now, delay=10)
    assert not capture.observe(q, provider_at=now, received_at=now, delay=None)
    q.market = "Tech100"
    assert not capture.observe(q, provider_at=now, received_at=now, delay=0)
