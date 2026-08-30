from __future__ import annotations

import io
import logging
from pathlib import Path

import runtime_logging


def _record(message: str, *, name: str = "pricegauger.autotrader.risk_control_v2", level: int = logging.WARNING):
    return logging.LogRecord(
        name=name,
        level=level,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=(),
        exc_info=None,
    )


def test_observer_risk_repeat_throttle_keeps_first_then_suppresses_repeat(monkeypatch):
    clock = iter((10.0, 11.0, 400.0))
    monkeypatch.setattr(runtime_logging.time, "monotonic", lambda: next(clock))
    throttle = runtime_logging.ObserverRiskRepeatThrottle(repeat_seconds=300)
    record = _record(
        "risk control position=4912__CfdOnIndex uic=4912 position_return=1.284% "
        "high=2.319% action=WOULD_CLOSE reason=TRAILING_STOP eligible=False"
    )

    assert throttle.filter(record) is True
    assert throttle.filter(record) is False
    assert throttle.filter(record) is True


def test_risk_throttle_does_not_hide_executable_or_unrelated_warnings():
    throttle = runtime_logging.ObserverRiskRepeatThrottle(repeat_seconds=300)
    executable = _record(
        "risk control position=p1 uic=1 position_return=-3.0% high=0.0% "
        "action=WOULD_CLOSE reason=HARD_STOP eligible=True"
    )
    unrelated = _record("some other production warning", name="pricegauger.other")

    assert throttle.filter(executable) is True
    assert throttle.filter(executable) is True
    assert throttle.filter(unrelated) is True


def test_runtime_logging_routes_info_stdout_and_warning_stderr(monkeypatch):
    stdout = io.StringIO()
    stderr = io.StringIO()
    monkeypatch.setattr(runtime_logging.sys, "stdout", stdout)
    monkeypatch.setattr(runtime_logging.sys, "stderr", stderr)

    root = logging.getLogger()
    old_handlers = list(root.handlers)
    old_level = root.level
    try:
        runtime_logging.configure_runtime_logging(level="INFO")
        logger = logging.getLogger("pricegauger.test.runtime_logging")
        logger.info("normal-info")
        logger.warning("real-warning")
        for handler in root.handlers:
            handler.flush()

        assert "normal-info" in stdout.getvalue()
        assert "normal-info" not in stderr.getvalue()
        assert "real-warning" in stderr.getvalue()
        assert "real-warning" not in stdout.getvalue()
    finally:
        root.handlers.clear()
        root.handlers.extend(old_handlers)
        root.setLevel(old_level)


def test_railway_logging_only_applies_to_long_running_worker_services(monkeypatch):
    called = []
    monkeypatch.setattr(runtime_logging, "configure_runtime_logging", lambda **_kwargs: called.append(True))

    monkeypatch.setenv("RAILWAY_SERVICE_NAME", "PriceGauger-stream")
    assert runtime_logging.configure_railway_runtime_logging_if_applicable() is True
    assert called == [True]

    called.clear()
    monkeypatch.setenv("RAILWAY_SERVICE_NAME", "pricegauger-web")
    assert runtime_logging.configure_railway_runtime_logging_if_applicable() is False
    assert called == []


def test_sitecustomize_keeps_streamlit_guard_out_of_worker_path():
    source = Path("sitecustomize.py").read_text(encoding="utf-8")
    configure = source.index("configure_railway_runtime_logging_if_applicable()")
    guard = source.index("if not _worker_logging_configured:")
    streamlit_import = source.index("import streamlit as st")
    assert configure < guard < streamlit_import
