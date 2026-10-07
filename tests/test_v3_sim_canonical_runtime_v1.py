from pathlib import Path
from types import SimpleNamespace

import autotrader_v3_sim_runtime_v1 as sim
from autotrader_v3_registry_v1 import sim_config_issues_v3


def test_sim_capabilities_fail_closed_instead_of_ignoring_settings():
    assert sim_config_issues_v3(
        strategy_key="macd", timeframe="15m", control_mode="Manuell", modifiers=()
    ) == ()
    issues=sim_config_issues_v3(
        strategy_key="macd", timeframe="Adaptiv", control_mode="Overseer",
        modifiers=("reset-on-loss", "impulse"),
    )
    text=" | ".join(issues)
    assert "Adaptiv" in text
    assert "Overseer" in text
    assert "reset-on-loss" in text
    assert "impulse" in text


def test_sim_state_key_is_physically_separate_from_live_instance():
    assert sim._sim_state_id_v3("pilot-1") == "sim:pilot-1"
    assert sim._sim_state_id_v3("pilot-1") != "pilot-1"


def test_sim_uses_canonical_instance_strategy_and_configured_timeframe(monkeypatch):
    instance=SimpleNamespace(
        pilot_key="pilot-1",strategy_key="macd-trailing-v1",
        instrument_id=99,market_name="US Tech 100 NAS",
    )
    config=SimpleNamespace(
        strategy_key="macd",timeframe="15m",control_mode="Manuell",modifiers=(),
    )
    calls={}

    monkeypatch.setattr(sim,"load_v3_runtime_instances_v1",lambda db_path: (instance,))
    monkeypatch.setattr(sim,"sim_authority_armed_v3",lambda *a,**k: True)
    monkeypatch.setattr(sim,"load_autotrader_config_v3",lambda *a,**k: config)
    monkeypatch.setattr(sim,"_record_sim_runtime_v3",lambda *a,**k: None)
    monkeypatch.setattr(
        sim,"_prepare_sim_decision_context_v3",
        lambda **kw: calls.setdefault("context",kw) and False,
    )

    class Store:
        def load_instrument_range(self,**kwargs):
            calls["range"]=kwargs
            return (SimpleNamespace(point=object()),)
    monkeypatch.setattr(sim,"CanonicalMarketBarStoreV2",lambda db_path: Store())

    def closed(points,*,market,timeframe_minutes):
        calls["closed"]=(market,timeframe_minutes)
        return ("bar",)
    def observations(closed_bars,*,timeframe_minutes):
        calls["observations"]=timeframe_minutes
        return (SimpleNamespace(),)
    monkeypatch.setattr(sim,"closed_bars_v2",closed)
    monkeypatch.setattr(sim,"macd_observations_v2",observations)

    def evaluate(**kwargs):
        calls["evaluate"]=kwargs
        return SimpleNamespace(is_new=True)
    monkeypatch.setattr(sim,"evaluate_strategy_bar_v3",evaluate)

    assert sim.run_v3_sim_cycle_v1(db_path="test.db") == 1
    assert calls["closed"] == ("US Tech 100 NAS",15)
    assert calls["observations"] == 15
    assert calls["context"]["strategy_key"] == "macd-trailing-v1"
    assert calls["context"]["timeframe_minutes"] == 15
    assert calls["evaluate"]["trader_id"] == "sim:pilot-1"
    assert calls["evaluate"]["strategy_key"] == "macd-trailing-v1"


def test_sim_source_has_no_v2_enrollment_or_fixed_5m_dependency():
    source=Path("autotrader_v3_sim_runtime_v1.py").read_text(encoding="utf-8")
    assert "load_active_strategy_enrollments_v2" not in source
    assert "timeframe_minutes=5" not in source
    assert "load_v3_runtime_instances_v1" in source
    assert "_sim_state_id_v3(instance.pilot_key)" in source
