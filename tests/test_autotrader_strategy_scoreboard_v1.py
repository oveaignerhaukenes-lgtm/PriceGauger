from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from autotrader_hybrid_replay_v1 import BENCHMARK_NAMES_V1
from autotrader_strategy_scoreboard_v1 import (
    REGIME_CHOPPY,
    REGIME_IMPULSE,
    REGIME_TREND,
    build_strategy_scoreboard_v1,
    classify_price_regime_v1,
)


def _index(count: int) -> pd.DatetimeIndex:
    return pd.date_range("2026-09-01T00:00:00Z", periods=count, freq="1min")


def test_regime_classifier_recognizes_trend_chop_and_impulse() -> None:
    trend = pd.Series([100.0 + i for i in range(60)], index=_index(60))
    assert classify_price_regime_v1(trend).label == REGIME_TREND

    chop_values = [100.0 + (1.0 if i % 2 else -1.0) for i in range(60)]
    chop = pd.Series(chop_values, index=_index(60))
    assert classify_price_regime_v1(chop).label == REGIME_CHOPPY

    impulse_values = [100.0] * 20 + [110.0] + [110.1 + (0.01 * i) for i in range(39)]
    impulse = pd.Series(impulse_values, index=_index(60))
    assert classify_price_regime_v1(impulse).label == REGIME_IMPULSE


def test_scoreboard_ranks_same_replay_windows_and_drawdown_inputs() -> None:
    index = _index(600)
    replay = pd.DataFrame(index=index)
    replay["PRICE"] = pd.Series([100.0 + (i * 0.02) for i in range(len(index))], index=index)
    for offset, name in enumerate(BENCHMARK_NAMES_V1):
        replay[name] = pd.Series([i * (0.001 + offset * 0.0001) for i in range(len(index))], index=index)
        replay[f"TARGET_{name}"] = pd.Series([1.0 if (i // 60) % 2 == 0 else -1.0 for i in range(len(index))], index=index)

    board = build_strategy_scoreboard_v1(
        replay,
        now=datetime(2026, 9, 1, 9, 59, tzinfo=timezone.utc),
    )
    assert set(board.metrics) == set(BENCHMARK_NAMES_V1)
    assert board.metrics["MACD1"]["6h"].return_pct > 0.0
    assert board.metrics["MACD1"]["6h"].max_drawdown_pct <= 0.0
    assert board.metrics["MACD1"]["6h"].switches >= 1
    assert set(board.regime_returns_7d["MACD2"]) == {"CHOPPY", "EVEN", "TREND", "IMPULSE"}


def test_tradingdesk_mounts_scoreboard_and_keeps_it_analysis_only() -> None:
    panel = Path("tradingdesk_automanage_panel_v2.py").read_text(encoding="utf-8")
    ui = Path("tradingdesk_strategy_scoreboard_v1.py").read_text(encoding="utf-8")
    replay = Path("autotrader_hybrid_replay_v1.py").read_text(encoding="utf-8")
    assert "render_tradingdesk_strategy_scoreboard_v1(context)" in panel
    assert '"MACD1"' in replay
    assert '"MACD5"' in replay
    assert "switch_live_strategy_v2" not in ui
    assert "request_manual_target_v2" not in ui
    assert "place_order(" not in ui
