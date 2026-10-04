from datetime import datetime, timezone

import skilled_money_workspace_v1 as workspace


def _sqlite_connect(tmp_path, monkeypatch):
    from database import connect as real_connect

    db_path = tmp_path / "skilled-money.db"
    monkeypatch.setattr(workspace, "connect", lambda: real_connect(db_path, force_sqlite=True))


def test_watchlist_is_provider_bound_but_canonical(tmp_path, monkeypatch) -> None:
    _sqlite_connect(tmp_path, monkeypatch)
    watch_id = workspace.add_watch_v1(
        canonical_market="NASDAQ100",
        display_name="US Tech 100",
        provider="saxo",
        provider_instrument_id=12345,
        asset_type="CfdOnIndex",
        symbol="USNAS100.I",
    )
    watches = workspace.list_watches_v1()
    assert len(watches) == 1
    assert watches[0].watch_id == watch_id
    assert watches[0].canonical_market == "NASDAQ100"
    assert watches[0].provider == "saxo"
    assert watches[0].provider_instrument_id == "12345"


def test_manual_event_keeps_t0_and_appends_later_revision(tmp_path, monkeypatch) -> None:
    _sqlite_connect(tmp_path, monkeypatch)
    watch_id = workspace.add_watch_v1(
        canonical_market="XAUUSD",
        display_name="Gold",
        provider="saxo",
        provider_instrument_id=99,
        asset_type="CfdOnFutures",
        symbol="GOLD",
    )
    t0 = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)
    event_id = workspace.create_manual_event_v1(
        watch_id=watch_id,
        event_started_at=t0,
        event_ended_at=None,
        move_summary="sharp move higher",
        question="what drove this move?",
    )
    assert workspace.append_revision_v1(
        event_id=event_id,
        summary="Later positioning data supports the initial flow hypothesis",
        evidence=[{"kind": "CONFIRMED", "label": "positioning"}],
    ) == 2
    events = workspace.list_events_v1()
    revisions = workspace.list_revisions_v1(event_id)
    assert events[0].question == "what drove this move?"
    assert [item["revision"] for item in revisions] == [1, 2]
    assert "Manuell hendelse" in revisions[0]["summary"]
    assert revisions[1]["evidence"][0]["kind"] == "CONFIRMED"


def test_disabling_watch_hides_it_without_deleting_event_history(tmp_path, monkeypatch) -> None:
    _sqlite_connect(tmp_path, monkeypatch)
    watch_id = workspace.add_watch_v1(
        canonical_market="BRENT",
        display_name="Brent",
        provider="saxo",
        provider_instrument_id=7,
    )
    event_id = workspace.create_manual_event_v1(
        watch_id=watch_id,
        event_started_at=datetime(2026, 10, 4, tzinfo=timezone.utc),
        event_ended_at=None,
        move_summary="large move",
    )
    workspace.set_watch_active_v1(watch_id, False)
    assert workspace.list_watches_v1() == ()
    assert workspace.list_events_v1()[0].event_id == event_id
