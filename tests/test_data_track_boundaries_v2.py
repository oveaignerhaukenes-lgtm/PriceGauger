from __future__ import annotations

from pathlib import Path


def _source(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_technical_track_has_no_context_or_execution_dependencies() -> None:
    source = "\n".join(
        _source(path)
        for path in (
            "technical_core_v2.py",
            "runtime_technical_producer_v2.py",
            "technical_interpreter_v2.py",
        )
    )
    forbidden = (
        "context_runtime_v2",
        "context_snapshot_v2",
        "news_context",
        "telegram_flow",
        "historical_engine",
        "decision_engine",
        "market_state_service",
        "autotrader_",
        "saxo_trading",
    )
    for dependency in forbidden:
        assert dependency not in source, f"technical track must not depend on {dependency}"


def test_context_adapter_does_not_read_technical_or_execution_state() -> None:
    source = _source("context_adapter_v2.py")
    forbidden = (
        "technical_core_v2",
        "technical_analysis",
        "technical_interpreter_v2",
        "autotrader_",
        "saxo_trading",
        "state_runtime_pipeline",
        "decision_engine",
    )
    for dependency in forbidden:
        assert dependency not in source, f"context track must not depend on {dependency}"


def test_cross_market_producer_is_observational_only() -> None:
    source = _source("cross_market_runtime.py")
    forbidden = (
        "response_divergence",
        "transmission_state",
        "information_state",
        "decision_state",
        "state_runtime_pipeline",
        "technical_core_v2",
        "context_snapshot_v2",
        "autotrader_",
    )
    for dependency in forbidden:
        assert dependency not in source, f"cross-market producer must not depend on {dependency}"


def test_execution_context_uses_identity_not_analysis_layers() -> None:
    source = "\n".join(
        _source(path)
        for path in (
            "autotrader_execution_context_v2.py",
            "autotrader_manual_execution.py",
        )
    )
    forbidden = (
        "technical_core_v2",
        "technical_interpreter_v2",
        "context_snapshot_v2",
        "news_context",
        "telegram_flow",
        "historical_engine",
        "decision_engine",
        "market_state_service",
    )
    for dependency in forbidden:
        assert dependency not in source, f"execution boundary must not depend on {dependency}"
