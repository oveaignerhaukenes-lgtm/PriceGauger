from __future__ import annotations

import pandas as pd

from gold_numeraire import (
    build_numeraire_frame,
    dollar_in_gold_index,
    latest_comparison,
    normalized_gold_ratio,
)


def _series(values: list[float]) -> pd.Series:
    return pd.Series(values, index=pd.date_range("2026-01-01", periods=len(values), freq="D"))


def test_dollar_in_gold_falls_when_gold_rises() -> None:
    gold = _series([100.0, 125.0, 200.0])
    result = dollar_in_gold_index(gold)
    assert result.iloc[0] == 100.0
    assert result.iloc[-1] == 50.0


def test_asset_can_rise_in_usd_but_fall_against_gold() -> None:
    asset = _series([100.0, 120.0])
    gold = _series([100.0, 150.0])
    result = normalized_gold_ratio(asset, gold)
    assert result.iloc[0] == 100.0
    assert result.iloc[-1] == 80.0


def test_comparison_reports_usd_and_gold_changes() -> None:
    asset = _series([100.0, 120.0])
    gold = _series([100.0, 150.0])
    comparison = latest_comparison(asset, gold)
    assert round(comparison["usd_change_pct"], 6) == 20.0
    assert round(comparison["gold_change_pct"], 6) == -20.0


def test_frame_includes_dollar_and_selected_assets() -> None:
    gold = _series([100.0, 110.0])
    spx = _series([100.0, 121.0])
    frame = build_numeraire_frame({"S&P 500": spx}, gold=gold)
    assert list(frame.columns) == ["US dollar", "S&P 500"]
    assert round(float(frame["S&P 500"].iloc[-1]), 6) == 110.0
