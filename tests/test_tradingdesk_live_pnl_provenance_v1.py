from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from autotrader_macd_timeframe_controls_v1 import MACD_CONTROL_STRATEGY_KEYS_V1
from tradingdesk_ui.charts.lightweight import pnl_provenance as provenance


ROOT = Path(__file__).resolve().parents[1]
START = datetime(2026, 9, 7, 8, 0, tzinfo=timezone.utc)


def _comparison():
    return SimpleNamespace(
        product_key="A1:4912:CfdOnIndex:77",
        started_at=START,
        as_of=START + timedelta(hours=3),
        live_realized=(
            SimpleNamespace(occurred_at=START, return_pct=0.0),
            SimpleNamespace(occurred_at=START + timedelta(hours=1), return_pct=1.25),
        ),
        live_epochs=(
            SimpleNamespace(
                pilot_key="pilot-5m",
                strategy_key=MACD_CONTROL_STRATEGY_KEYS_V1[5],
                started_at=START,
                ended_at=START + timedelta(hours=2),
            ),
            SimpleNamespace(
                pilot_key="pilot-2m",
                strategy_key=MACD_CONTROL_STRATEGY_KEYS_V1[2],
                started_at=START + timedelta(hours=2),
                ended_at=None,
            ),
        ),
    )


def test_strategy_epochs_are_explicit_and_keep_human_labels(monkeypatch) -> None:
    class Db:
        def execute(self, *_args, **_kwargs):
            return SimpleNamespace(fetchall=lambda: [])

    class Ctx:
        def __enter__(self):
            return Db()

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(provenance, "connect", lambda: Ctx())
    comparison = _comparison()
    epochs = provenance.build_live_pnl_strategy_epochs_v1(comparison)
    events = provenance.build_live_pnl_provenance_events_v1(comparison)

    assert len(epochs) == 2
    assert "5m" in epochs[0]["label"]
    assert "2m" in epochs[1]["label"]
    strategy_events = [item for item in events if item["kind"] == "STRATEGY_ACTIVATION"]
    assert [item["time"] for item in strategy_events] == [
        int(START.timestamp()),
        int((START + timedelta(hours=2)).timestamp()),
    ]
    assert all(item["label"].startswith("STRAT ·") for item in strategy_events)


def test_manual_saxo_marker_requires_persisted_foreign_order_provenance(monkeypatch) -> None:
    manual_at = START + timedelta(hours=1, minutes=30)

    class Db:
        def execute(self, sql, _parameters):
            assert "UNKNOWN_WORKING_ORDER" in sql
            assert "UNEXPECTED_POSITION_ORIGIN" in sql
            return SimpleNamespace(
                fetchall=lambda: [
                    {
                        "kind": "UNKNOWN_WORKING_ORDER",
                        "first_seen_at": manual_at,
                        "external_reference": "manual-ref",
                        "order_id": "saxo-order-1",
                        "net_position_id": None,
                        "details": "Foreign/manual working order left untouched",
                    }
                ]
            )

    class Ctx:
        def __enter__(self):
            return Db()

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(provenance, "connect", lambda: Ctx())
    events = provenance.build_live_pnl_provenance_events_v1(_comparison())
    manual = [item for item in events if item["kind"] == "MANUAL_SAXO"]

    assert len(manual) == 1
    assert manual[0]["label"] == "MANUAL / SAXO"
    assert manual[0]["source_kind"] == "UNKNOWN_WORKING_ORDER"
    assert manual[0]["time"] == int(manual_at.timestamp())
    assert manual[0]["value"] == 1.25
    assert "manual-ref" in manual[0]["detail"]
    assert "saxo-order-1" in manual[0]["detail"]


def test_unexpected_position_origin_is_marked_manual_saxo(monkeypatch) -> None:
    manual_at = START + timedelta(hours=2, minutes=15)

    class Db:
        def execute(self, _sql, _parameters):
            return SimpleNamespace(
                fetchall=lambda: [
                    {
                        "kind": "UNEXPECTED_POSITION_ORIGIN",
                        "first_seen_at": manual_at,
                        "external_reference": None,
                        "order_id": None,
                        "net_position_id": "4912__CfdOnIndex",
                        "details": "Unmanaged Saxo position has no current PG OPEN provenance",
                    }
                ]
            )

    class Ctx:
        def __enter__(self):
            return Db()

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(provenance, "connect", lambda: Ctx())
    manual = [
        item
        for item in provenance.build_live_pnl_provenance_events_v1(_comparison())
        if item["kind"] == "MANUAL_SAXO"
    ]

    assert len(manual) == 1
    assert manual[0]["source_kind"] == "UNEXPECTED_POSITION_ORIGIN"
    assert manual[0]["label"] == "MANUAL / SAXO"
    assert "4912__CfdOnIndex" in manual[0]["detail"]


def test_strategy_lab_renders_live_provenance_on_baseline_chart() -> None:
    source = (
        ROOT / "tradingdesk_ui" / "charts" / "lightweight" / "pnl_strategy_lab.py"
    ).read_text(encoding="utf-8")
    assert '"live_epochs": build_live_pnl_strategy_epochs_v1(comparison)' in source
    assert '"live_events": build_live_pnl_provenance_events_v1(comparison)' in source
    assert "LWC.createSeriesMarkers(carrier, markers" in source
    assert "Aktiv strategi:" in source
    assert "MANUAL / SAXO" in source
    assert "eksplisitt broker-provenance" in source
