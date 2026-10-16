"""Causal-input, same-clock regime research with explicit history limitations."""
from datetime import datetime, timedelta, timezone
from logging import Logger
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from tech100_regime_forensics_20261016 import (
    _sample_regime, emit_tech100_regime_study, quantify_market_window,
)


def _bars(closes, *, start=datetime(2026, 10, 16, 11, 48, tzinfo=timezone.utc)):
    return [
        SimpleNamespace(
            bar_time=(start + timedelta(minutes=i)).isoformat(),
            close=float(x), high=float(x) + 1.0, low=float(x) - 1.0,
        )
        for i, x in enumerate(closes)
    ]


def test_directional_regime_high_efficiency_low_reversals():
    bars = _bars([100 + i for i in range(90)])
    result = quantify_market_window(
        bars, start=bars[0].bar_time, end=bars[-1].bar_time,
    )
    assert result["status"] == "OK"
    assert result["coverage_pct"] == 100
    assert result["gaps"] == 0
    assert result["efficiency_ratio"] == 1.0
    assert result["sign_reversal_rate"] == 0.0
    assert result["rolling30_regime_pct"]["TREND"] == 100.0
    assert result["volatility_1m_bp"] >= 0


def test_alternating_regime_low_efficiency_maximum_flip_rate():
    bars = _bars([100 + 5 * (i % 2) for i in range(90)])
    result = quantify_market_window(
        bars, start=bars[0].bar_time, end=bars[-1].bar_time,
    )
    assert result["status"] == "OK"
    assert result["efficiency_ratio"] < 0.02
    assert result["sign_reversal_rate"] == 1.0
    assert result["rolling30_regime_pct"]["CHOPPY"] == 100.0
    assert _sample_regime([100 + 5 * (i % 2) for i in range(30)])[0] == "CHOPPY"


def test_no_fabricated_candles_and_no_future_data():
    full = _bars([100 + i for i in range(80)])
    missing = full[:20] + full[21:]
    original = quantify_market_window(
        missing, start=full[0].bar_time, end=full[59].bar_time,
    )
    with_future = quantify_market_window(
        missing + _bars([9000], start=datetime(2026, 10, 16, 13, 15, tzinfo=timezone.utc)),
        start=full[0].bar_time, end=full[59].bar_time,
    )
    assert original == with_future
    assert original["gaps"] == 1
    assert original["coverage_pct"] < 100
    assert original["coverage_warning"] is True


def test_study_is_read_only_and_worker_does_not_change_saxo_authority():
    body = Path("tech100_regime_forensics_20261016.py").read_text(encoding="utf-8")
    worker = Path("live_sim_lab_worker_v1.py").read_text(encoding="utf-8")
    assert "FROM autotrader_v3_execution_events" in body
    assert "load_instrument_range" in body
    assert "WHERE enabled=TRUE AND uic=4912" in body
    assert "REGIME_STUDY_WINDOW" in body
    assert "emit_tech100_regime_study" in worker
    for forbidden in ("INSERT INTO", "UPDATE autotrader", "place_order(", "set_live_enabled_v3"):
        assert forbidden not in body
    assert "Saxo" not in body.split("from __future__ import annotations", 1)[1].split("def utc(", 1)[0]


def test_emit_reports_unavailable_without_pretending_to_have_metrics(monkeypatch):
    import tech100_regime_forensics_20261016 as module
    monkeypatch.setattr(module, "production_tech100_regime_study", lambda **kw:
                        {"status": "NO_ACTIVE_TECH100_INSTRUMENT"})
    logger = Mock(spec=Logger)
    assert emit_tech100_regime_study(logger) is False
    assert logger.info.call_count == 1
    assert "REGIME_STUDY_META" in logger.info.call_args.args[0]
