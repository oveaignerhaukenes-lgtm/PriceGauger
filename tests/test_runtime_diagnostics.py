from __future__ import annotations

from database import connect
from runtime_diagnostics import build_runtime_diagnostic_report


def test_diagnostic_identifies_missing_decision_state(tmp_path):
    db_path = tmp_path / "diagnostics.sqlite3"
    with connect(db_path) as db:
        db.executescript(
            """
            CREATE TABLE telegram_flow_posts (
                message_id TEXT PRIMARY KEY,
                published_at TEXT NOT NULL
            );
            CREATE TABLE telegram_flow_snapshots (
                as_of TEXT PRIMARY KEY
            );
            CREATE TABLE information_state_snapshots (
                snapshot_id TEXT PRIMARY KEY,
                as_of TEXT NOT NULL
            );
            CREATE TABLE decision_state_snapshots (
                snapshot_id TEXT PRIMARY KEY,
                market TEXT NOT NULL,
                as_of TEXT NOT NULL
            );
            CREATE TABLE market_mover_alerts (
                alert_id TEXT PRIMARY KEY,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE overview_summaries (
                information_snapshot_id TEXT PRIMARY KEY,
                as_of TEXT NOT NULL
            );
            """
        )
        db.execute(
            "INSERT INTO telegram_flow_posts(message_id, published_at) VALUES (?, ?)",
            ("1", "2026-07-31T10:00:00+00:00"),
        )
        db.execute(
            "INSERT INTO telegram_flow_snapshots(as_of) VALUES (?)",
            ("2026-07-31T10:01:00+00:00",),
        )
        db.execute(
            "INSERT INTO information_state_snapshots(snapshot_id, as_of) VALUES (?, ?)",
            ("info-1", "2026-07-31T10:01:00+00:00"),
        )

    report = build_runtime_diagnostic_report(db_path)

    assert any("Decision State bootstrap has not completed" in item for item in report.diagnosis)
    assert report.decision_markets == ()


def test_diagnostic_reports_complete_chain(tmp_path):
    db_path = tmp_path / "diagnostics.sqlite3"
    with connect(db_path) as db:
        db.executescript(
            """
            CREATE TABLE telegram_flow_posts (
                message_id TEXT PRIMARY KEY,
                published_at TEXT NOT NULL
            );
            CREATE TABLE telegram_flow_snapshots (
                as_of TEXT PRIMARY KEY
            );
            CREATE TABLE information_state_snapshots (
                snapshot_id TEXT PRIMARY KEY,
                as_of TEXT NOT NULL
            );
            CREATE TABLE decision_state_snapshots (
                snapshot_id TEXT PRIMARY KEY,
                market TEXT NOT NULL,
                as_of TEXT NOT NULL
            );
            CREATE TABLE market_mover_alerts (
                alert_id TEXT PRIMARY KEY,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE overview_summaries (
                information_snapshot_id TEXT PRIMARY KEY,
                as_of TEXT NOT NULL
            );
            """
        )
        db.execute(
            "INSERT INTO telegram_flow_posts(message_id, published_at) VALUES (?, ?)",
            ("1", "2026-07-31T10:00:00+00:00"),
        )
        db.execute(
            "INSERT INTO telegram_flow_snapshots(as_of) VALUES (?)",
            ("2026-07-31T10:01:00+00:00",),
        )
        db.execute(
            "INSERT INTO information_state_snapshots(snapshot_id, as_of) VALUES (?, ?)",
            ("info-1", "2026-07-31T10:01:00+00:00"),
        )
        for market in ("Brent", "DXY", "Gold", "Natural Gas", "Silver"):
            db.execute(
                "INSERT INTO decision_state_snapshots(snapshot_id, market, as_of) VALUES (?, ?, ?)",
                (f"decision-{market}", market, "2026-07-31T10:01:00+00:00"),
            )

    report = build_runtime_diagnostic_report(db_path)

    assert report.decision_markets == ("Brent", "DXY", "Gold", "Natural Gas", "Silver")
    assert report.diagnosis == (
        "The persisted Telegram → Information State → Decision State chain is complete.",
    )
