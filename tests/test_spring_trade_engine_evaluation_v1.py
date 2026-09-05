from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from spring_trade_engine.research.forward_labels import build_forward_label_v1


ROOT = Path(__file__).resolve().parents[1]
START = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)


@dataclass(frozen=True)
class _Bar:
    bar_time: datetime
    high: float
    low: float
    close: float


def test_forward_label_records_terminal_return_and_path_excursions() -> None:
    bars = (
        _Bar(START + timedelta(minutes=1), 101.0, 99.5, 100.5),
        _Bar(START + timedelta(minutes=2), 102.0, 100.0, 101.5),
        _Bar(START + timedelta(minutes=3), 101.8, 98.0, 99.0),
        _Bar(START + timedelta(minutes=4), 100.5, 98.5, 100.0),
        _Bar(START + timedelta(minutes=5), 101.2, 99.0, 101.0),
    )

    label = build_forward_label_v1(
        instrument_id=7,
        observed_at=START,
        start_price=100.0,
        horizon_minutes=5,
        future_bars=bars,
    )

    assert label is not None
    assert label.realized_at == START + timedelta(minutes=5)
    assert label.return_pct == pytest.approx(1.0)
    assert label.max_favorable_excursion_pct == pytest.approx(2.0)
    assert label.max_adverse_excursion_pct == pytest.approx(-2.0)


def test_forward_label_refuses_incomplete_horizon() -> None:
    label = build_forward_label_v1(
        instrument_id=7,
        observed_at=START,
        start_price=100.0,
        horizon_minutes=5,
        future_bars=(
            _Bar(START + timedelta(minutes=1), 101.0, 99.0, 100.0),
            _Bar(START + timedelta(minutes=2), 101.0, 99.0, 100.0),
        ),
    )
    assert label is None


def test_spring_evaluation_is_observational_and_chart_is_consumer_side_link() -> None:
    runtime_source = (ROOT / "spring_trade_engine" / "runtime" / "observer_runtime.py").read_text(encoding="utf-8")
    evaluation_source = (ROOT / "spring_trade_engine" / "persistence" / "evaluation_store.py").read_text(encoding="utf-8")
    chart_source = (ROOT / "autotrader_pnl_chart_v2.py").read_text(encoding="utf-8")

    assert "pg_v2_spring_forward_labels" in evaluation_source
    assert "pg_v2_spring_runtime_coverage" in evaluation_source
    assert "pg_v2_spring_episode_candidates" in evaluation_source
    assert "persist_turning_point_v1" in runtime_source
    assert "collect_forward_labels_v1" in runtime_source
    assert "load_spring_observations_v1" in chart_source
    assert "Spring · blind observasjon" in chart_source
    assert "autotrader_live_open" not in runtime_source
    assert "autotrader_live_close" not in runtime_source
    assert "SaxoClient" not in runtime_source
