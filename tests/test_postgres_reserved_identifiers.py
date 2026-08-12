from __future__ import annotations

from types import SimpleNamespace

import response_divergence
import transmission_state


class _CaptureConnection:
    def __init__(self) -> None:
        self.scripts: list[str] = []
        self.queries: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def executescript(self, script: str) -> None:
        self.scripts.append(script)

    def execute(self, sql: str, parameters=()):
        self.queries.append(sql)
        return SimpleNamespace(fetchone=lambda: None)


def _snapshot(**values):
    class Snapshot(SimpleNamespace):
        def to_record(self):
            return dict(self.__dict__)

    return Snapshot(**values)


def test_response_divergence_store_quotes_postgres_reserved_window(monkeypatch):
    connection = _CaptureConnection()
    monkeypatch.setattr(response_divergence, "connect", lambda path: connection)

    store = response_divergence.ResponseDivergenceStore("ignored")
    store.save(
        _snapshot(
            divergence_id="div:test",
            market="Silver",
            window="15m",
            as_of="2026-08-12T18:00:00+00:00",
            information_snapshot_id="info:test",
            cross_market_snapshot_id="cross:test",
            status="DIVERGENT",
        )
    )

    assert '"window" TEXT NOT NULL' in connection.scripts[0]
    assert 'market, "window", as_of' in connection.queries[0]
    assert "market, window, as_of" not in connection.queries[0]


def test_transmission_state_store_quotes_postgres_reserved_window(monkeypatch):
    connection = _CaptureConnection()
    monkeypatch.setattr(transmission_state, "connect", lambda path: connection)

    store = transmission_state.TransmissionStateStore("ignored")
    store.save(
        _snapshot(
            transmission_id="transmission:test",
            market="Silver",
            window="15m",
            as_of="2026-08-12T18:00:00+00:00",
            response_divergence_id="div:test",
            resolution_status="UNRESOLVED",
            dominant_channel=None,
        )
    )

    assert '"window" TEXT NOT NULL' in connection.scripts[0]
    assert 'market, "window", as_of' in connection.queries[0]
    assert "market, window, as_of" not in connection.queries[0]
