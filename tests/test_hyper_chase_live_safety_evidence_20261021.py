"""Safety regression for 10s HyperChase LIVE with optional 1m modifiers.

No Saxo broker, LIVE account or network dependency in these tests.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import autotrader_v3_live_runtime_v1 as runtime
from autotrader_v3_domain import TargetInventoryV3
from autotrader_v3_whipsaw_live_v1 import VolatilityPauseLiveModifierV3


def test_hyper_safety_feed_caches_once_per_utc_minute(monkeypatch):
    calls = []
    class FakeStore:
        def __init__(self, db_path):
            assert db_path == "dummy.db"

        def load_instrument_range(self, *, instrument_id, start, end, limit):
            calls.append((instrument_id, start, end, limit))
            return [SimpleNamespace(point=f"closed-{len(calls)}")]

    monkeypatch.setattr(runtime, "CanonicalMarketBarStoreV2", FakeStore)
    runtime._hyper_safety_1m_points_v3.cache_clear()
    minute = datetime(2026, 10, 21, 2, 10, tzinfo=timezone.utc)
    try:
        a = runtime._hyper_safety_1m_points_v3("dummy.db", 7, minute)
        b = runtime._hyper_safety_1m_points_v3("dummy.db", 7, minute)
        c = runtime._hyper_safety_1m_points_v3("dummy.db", 7, minute + timedelta(minutes=1))
        assert a == b == ("closed-1",)
        assert c == ("closed-2",)
        assert len(calls) == 2
        assert calls[0] == (7, minute - timedelta(hours=3), minute, 240)
    finally:
        runtime._hyper_safety_1m_points_v3.cache_clear()


def test_hyper_signal_still_quote_driven_and_modifier_uses_closed_bars():
    src = Path("autotrader_v3_live_runtime_v1.py").read_text(encoding="utf-8")
    assert "decision=evaluate_hyper_chase_live_v3(" in src
    assert "safety_points=_hyper_safety_1m_points_v3(" in src
    assert "if e.strategy_key in HYPER_RUNTIME_KEYS:" in src
    assert "closed_1m=closed_bars_v2(" in src
    assert "if 'volatility-pause' in config.modifiers:" in src
    assert "data_ok=vol_ok,high_vol=high_vol" in src


def test_unavailable_modifier_evidence_still_fails_closed():
    # This guard must never blindly allow a new entry just because
    # closed-bar safety data is missing.
    missing = VolatilityPauseLiveModifierV3(
        actual_inventory=0.0, data_ok=False, high_vol=False)
    blocked, reason = missing.apply(None, TargetInventoryV3(0.01))
    assert blocked.amount == 0.0
    assert "blocked" in reason
    # On an opposite signal while long, risk may decrease to FLAT.
    opposite = VolatilityPauseLiveModifierV3(
        actual_inventory=0.01, data_ok=False, high_vol=False)
    flat, reason = opposite.apply(None, TargetInventoryV3(-0.01))
    assert flat.amount == 0.0
    assert "FLAT" in reason
    # A successful independent safety assessment must not veto the base
    # HyperChase target, unlike the current always-empty bars input.
    normal = VolatilityPauseLiveModifierV3(
        actual_inventory=0.0, data_ok=True, high_vol=False)
    allowed, _ = normal.apply(None, TargetInventoryV3(-0.01))
    assert allowed.amount == -0.01
