"""Cost gates must not alter live risk, Saxo account truth or user-selected trading."""
from pathlib import Path

import pytest
import realtime_worker
import live_sim_lab_worker_v1


@pytest.mark.parametrize("value,expected",[
    (None,False),("",False),("false",False),("0",False),
    ("TRUE",True),("1",True),(" on ",True),
])
def test_legacy_shadow_loops_are_explicit_opt_in(monkeypatch,value,expected):
    key="PRICEGAUGER_LEGACY_SHADOW_RESEARCH"
    if value is None:
        monkeypatch.delenv(key,raising=False)
    else:
        monkeypatch.setenv(key,value)
    assert realtime_worker.legacy_shadow_research_enabled() is expected


@pytest.mark.parametrize("feature",[
    "PRICEGAUGER_LAB_AI_TECH_ENABLED","PRICEGAUGER_LAB_AI_PAIRS_ENABLED",
])
def test_llm_paper_loop_requires_feature_optin(monkeypatch,feature):
    monkeypatch.delenv(feature,raising=False)
    assert live_sim_lab_worker_v1.optional_paper_ai_enabled(feature) is False
    monkeypatch.setenv(feature,"on")
    assert live_sim_lab_worker_v1.optional_paper_ai_enabled(feature) is True
    monkeypatch.setenv(feature,"0")
    assert live_sim_lab_worker_v1.optional_paper_ai_enabled(feature) is False


def test_arbitrary_flag_cannot_bypass_paper_gate():
    with pytest.raises(ValueError):
        live_sim_lab_worker_v1.optional_paper_ai_enabled("OPENAI_API_KEY")


def test_risk_and_live_execution_start_outside_shadow_research_gate():
    src=Path("realtime_worker.py").read_text()
    main=src[src.index("def main()"):]
    enabled=main.index("    if legacy_shadow_research_enabled():")
    risk=main.index("    _start_autotrader_risk_control(")
    legacy=main.index("        _start_autotrader_cocktail_mode_1_shadow(")
    assert enabled < legacy < risk
    assert "    _start_autotrader_strategy(" in main
    assert "    _start_autotrader_live_close(" in main
    assert "    _start_autotrader_live_open(" in main
    assert "    _start_autotrader_equity_reconciliation(" in main
    assert "    _start_autotrader_runtime_watchdog(" in main
    assert "    _start_manual_saxo_trade_markers(" in main


def test_live_sim_and_hyper_paper_still_run_unconditionally():
    src=Path("live_sim_lab_worker_v1.py").read_text()
    main=src[src.index("def main():"):]
    assert main.index("    hyper_thread.start()") < main.index(
        "    if optional_paper_ai_enabled(")
    assert "        count = run_once(db_path=args.db)" in main


def test_freshness_probe_no_long_history_scan():
    src=Path("realtime_worker.py").read_text()
    probe=src[src.index("def _run_freshness_probe("):src.index("def main()")]
    assert "timedelta(minutes=15)" in probe
    assert "limit=20" in probe
    assert "limit=5000" not in probe
