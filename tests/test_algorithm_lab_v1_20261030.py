"""Regression tests for isolated Algorithm Lab v1."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from pathlib import Path

import pytest

from algorithm_lab_v1 import PRESETS, LabCosts, replay_algorithm, validate_plan
from algorithm_lab_ai_v1 import _extract_json
from strategy_lab_v2_ai import LabAIError


START = datetime(2026, 10, 1, tzinfo=timezone.utc)


def bars(n=1400, direction=1, gap_at=None):
    out = []
    previous = 10000.
    for i in range(n):
        t = START + timedelta(minutes=i + (10 if gap_at is not None and i >= gap_at else 0))
        nxt = previous + direction * 2.0
        out.append(SimpleNamespace(
            bar_time=t, open=previous, high=max(previous, nxt),
            low=min(previous, nxt), close=nxt))
        previous = nxt
    return out


def run(name, candles=None, *, start=START, end=None, **cost_kwargs):
    candles = candles if candles is not None else bars()
    return replay_algorithm(
        plan=PRESETS[name], bars=candles,
        costs=LabCosts(point_value_nok=100., lot_size=.01,
                       starting_nav_nok=10000., spread_bps=0.,
                       slippage_bps=0., **cost_kwargs),
        start_at=start, end_at=end or START + timedelta(minutes=1400))


@pytest.mark.parametrize("name", tuple(PRESETS))
def test_presets_are_strictly_valid(name):
    assert validate_plan(PRESETS[name]) == PRESETS[name]


@pytest.mark.parametrize("extra", (
    {"python": "import os"},
    {"regime_rule": "__import__('os')"},
    {"lookback": True},
    {"entry_bps": float("nan")},
))
def test_invalid_ai_fields_or_values_rejected(extra):
    item = dict(PRESETS["Trend Long / Flat"])
    item.update(extra)
    with pytest.raises(ValueError):
        validate_plan(item)


def test_30m_macro_long_only_after_actual_warmup():
    r = run("Trend Long / Flat")
    assert r.source_bars == 1400
    assert r.warmup_30m_bars >= 35
    assert any(t.action == "OPEN" for t in r.trades)
    assert all(t.after >= 0 for t in r.trades)
    assert all(x.at >= START for x in r.points)
    assert r.pnl_nok > 0


def test_30m_macro_short_only():
    r = run("Trend Short / Flat", candles=bars(direction=-1))
    assert any(t.action == "OPEN" for t in r.trades)
    assert all(t.after <= 0 for t in r.trades)


def test_insufficient_30m_history_cannot_open_trend():
    r = run("Trend Long / Flat", candles=bars(900),
            end=START+timedelta(minutes=900))
    assert not r.trades
    assert r.pnl_nok == 0


def test_impulse_entry_not_filled_on_signal_close():
    r = run("Impulse Up Collector", candles=bars(60, direction=12),
            end=START+timedelta(minutes=60))
    first_open = next(t for t in r.trades if t.action == "OPEN")
    # A 1m momentum signal cannot fill at its own completed candle.
    assert first_open.at >= START+timedelta(minutes=2)
    assert all(t.after >= 0 for t in r.trades)


def test_no_fictitious_gap_profit_and_reset():
    r = run("Impulse Up Collector", candles=bars(80, direction=12, gap_at=20),
            end=START+timedelta(minutes=90))
    assert r.gaps == 1
    assert any(t.action == "GAP_FLAT" for t in r.trades)


def test_costs_reduce_paper_profit():
    base = run("Impulse Up Collector", candles=bars(120, direction=12),
               end=START+timedelta(minutes=120))
    costly = run("Impulse Up Collector", candles=bars(120),
                 end=START+timedelta(minutes=120),
                 commission_nok=4.)
    assert costly.pnl_nok < base.pnl_nok
    assert costly.total_cost_nok > base.total_cost_nok


def test_selected_pnl_does_not_import_warmup_profit():
    r = run("Impulse Up Collector", start=START+timedelta(minutes=100),
            end=START+timedelta(minutes=120))
    assert r.points[0].at >= START+timedelta(minutes=100)
    assert r.pnl_nok < 1000


def test_ai_schema_validation_and_no_live_access():
    payload = {"plan": PRESETS["Impulse Down Collector"],
               "rationale": "Et eksempel", "test_notes": "Test mot kostnader"}
    assert _extract_json(json.dumps(payload))["plan"]["side"] == "short"
    payload["plan"] = {**PRESETS["Impulse Down Collector"],
                       "code": "open('/tmp/secrets')"}
    with pytest.raises(LabAIError):
        _extract_json(json.dumps(payload))
    page = Path("pages/0_Algorithm_Lab.py").read_text(encoding="utf8")
    assert "eval(" not in page and "exec(" not in page
    assert "ORDER" not in page.upper() or "ingen LIVE-ordre" in page
    assert 'Algoritmelab' in Path("navigation_config.py").read_text(encoding="utf8")
