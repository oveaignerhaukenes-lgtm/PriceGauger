from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from autotrader_macd_supervisor_memory_v1 import aggregate_memory_edge_v1, SupervisorMemoryEpisodeV1
from tradingdesk_macd_supervisor_lab_v1 import AI_NAME, RULE_NAME, _ai_variant


@dataclass(frozen=True)
class _Switch:
    at: pd.Timestamp
    price: float
    target: int


def test_memory_edge_uses_forward_outcomes() -> None:
    episodes = (
        SupervisorMemoryEpisodeV1(1, 7, pd.Timestamp("2026-09-11T10:00:00Z").to_pydatetime(), 1, .5, .5, .4, .3, "a", {}, {}, {30: 1.2}),
        SupervisorMemoryEpisodeV1(2, 7, pd.Timestamp("2026-09-11T11:00:00Z").to_pydatetime(), -1, .5, .5, -.4, -.3, "b", {}, {}, {30: -0.2}),
    )
    result = aggregate_memory_edge_v1(episodes, horizon_minutes=30)
    assert result["count"] == 2.0
    assert result["mean_pct"] == 0.5
    assert result["win_rate_pct"] == 50.0


def test_ai_variant_can_hold_or_override_rule_switches() -> None:
    index = pd.date_range("2026-09-11T10:00:00Z", periods=4, freq="min")
    frame = pd.DataFrame({"PRICE": [100, 101, 100, 99], "TARGET": [1, 1, -1, -1]}, index=index)
    switches = (_Switch(index[0], 100.0, 1), _Switch(index[2], 100.0, -1))
    hold = {str(index[2]): {"target": 0}}
    held, events = _ai_variant(frame, switches, hold)
    assert list(held["TARGET"]) == [1.0, 1.0, 1.0, 1.0]
    assert len(events) == 1
    override = {str(index[2]): {"target": -1}}
    changed, events = _ai_variant(frame, switches, override)
    assert list(changed["TARGET"]) == [1.0, 1.0, -1.0, -1.0]
    assert len(events) == 2


def test_lab_exposes_both_models_and_keeps_reflection_analysis_only() -> None:
    source = Path("tradingdesk_macd_supervisor_lab_v1.py").read_text(encoding="utf-8")
    reflection = Path("autotrader_macd_supervisor_reflection_v1.py").read_text(encoding="utf-8")
    memory = Path("autotrader_macd_supervisor_memory_v1.py").read_text(encoding="utf-8")
    assert RULE_NAME in source
    assert AI_NAME in source
    assert "Vis / plott modeller" in source
    assert "Reflekter nye skift" in source
    assert "pg_v2_macd_supervisor_memory" in memory
    assert "pg_v2_macd_supervisor_reflections" in memory
    assert "recommended_target" in reflection
    assert "trade/v2/orders" not in reflection
    assert "request_manual_target_v2" not in reflection
    assert "switch_live_strategy_v2" not in reflection
