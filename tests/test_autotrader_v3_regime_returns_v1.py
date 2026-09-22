from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from autotrader_v3_regime_returns_v1 import build_regime_return_cells_v3, build_relative_return_lines_v3


def _point(day, equity):
    return SimpleNamespace(closed_at=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=day), equity=equity)


def test_regime_returns_rebase_each_bucket_instead_of_showing_cumulative_drawdown():
    series = SimpleNamespace(
        strategy_key="strategy-a",
        points=(
            _point(0, 100),
            _point(1, 80),
            _point(2, 88),
            _point(3, 96.8),
        ),
    )
    comparison = SimpleNamespace(paper_series=(series,))
    cells = build_regime_return_cells_v3(comparison, bucket_count=2)
    assert len(cells) == 2
    assert cells[0].return_pct == pytest.approx(-20.0)
    # The second regime is positive relative to its own starting equity even though
    # cumulative equity remains below the original 100 seed.
    assert cells[1].return_pct == pytest.approx(21.0)


def test_regime_chart_builds_comparable_cells_for_multiple_strategies():
    a = SimpleNamespace(strategy_key="a", points=(_point(0, 100), _point(1, 110), _point(2, 99)))
    b = SimpleNamespace(strategy_key="b", points=(_point(0, 100), _point(1, 95), _point(2, 104.5)))
    cells = build_regime_return_cells_v3(SimpleNamespace(paper_series=(a, b)), bucket_count=2)
    assert {cell.strategy_key for cell in cells} == {"a", "b"}
    assert any(cell.return_pct > 0 for cell in cells)
    assert any(cell.return_pct < 0 for cell in cells)


def test_regime_bucket_count_must_be_positive():
    with pytest.raises(ValueError):
        build_regime_return_cells_v3(SimpleNamespace(paper_series=()), bucket_count=0)


def test_relative_lines_start_at_zero_and_preserve_continuous_distance_from_zero():
    series = SimpleNamespace(
        strategy_key="strategy-a",
        points=(_point(0, 100), _point(1, 80), _point(2, 88), _point(3, 110)),
    )
    points = build_relative_return_lines_v3(SimpleNamespace(paper_series=(series,)))
    assert [item.return_pct for item in points] == pytest.approx([0.0, -20.0, -12.0, 10.0])
