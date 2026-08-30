from __future__ import annotations

from pathlib import Path

import runtime_entrypoint


def test_runtime_entrypoint_configures_logging_before_target(monkeypatch):
    events: list[object] = []
    monkeypatch.setattr(
        runtime_entrypoint,
        "configure_runtime_logging",
        lambda: events.append("logging"),
    )

    def fake_run_path(target: str, *, run_name: str):
        events.append(("run", target, run_name, tuple(runtime_entrypoint.sys.argv)))

    monkeypatch.setattr(runtime_entrypoint.runpy, "run_path", fake_run_path)

    runtime_entrypoint.run_target(["realtime_worker.py", "--refresh-ms", "1000"])

    assert events == [
        "logging",
        (
            "run",
            "realtime_worker.py",
            "__main__",
            ("realtime_worker.py", "--refresh-ms", "1000"),
        ),
    ]


def test_runtime_entrypoint_rejects_missing_or_non_python_target():
    for argv in ([], ["not-python"]):
        try:
            runtime_entrypoint.run_target(argv)
        except SystemExit:
            pass
        else:
            raise AssertionError(f"expected SystemExit for {argv!r}")


def test_railway_worker_configs_use_explicit_logging_launcher():
    stream = Path("railway.stream.toml").read_text(encoding="utf-8")
    worker = Path("railway.worker.toml").read_text(encoding="utf-8")

    assert "python runtime_entrypoint.py realtime_worker.py" in stream
    assert "python runtime_entrypoint.py telegram_multi_worker.py" in worker
    assert "python realtime_worker.py" not in stream
    assert "python telegram_multi_worker.py" not in worker
