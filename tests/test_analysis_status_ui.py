from __future__ import annotations

from analysis_status import AnalysisStepStatus
from analysis_status_ui import render_analysis_status


def test_analysis_status_renders_ordered_worker_steps():
    html = render_analysis_status(
        (
            AnalysisStepStatus(
                step_key="telegram_fetch",
                label="Telegram innhentet",
                status="COMPLETE",
                detail="12 poster hentet",
                updated_at="2026-08-01T00:12:00+00:00",
            ),
            AnalysisStepStatus(
                step_key="technical_state",
                label="Teknisk analyse",
                status="PENDING",
                detail="Ikke koblet inn ennå",
                updated_at="2026-08-01T00:12:01+00:00",
            ),
        )
    )

    assert "Analyseflyt" in html
    assert "Telegram innhentet" in html
    assert "Teknisk analyse" in html
    assert "Ferdig" in html
    assert "Venter" in html
    assert "12 poster hentet" in html
    assert "\n" not in html
    assert not any(line.startswith("    <") for line in html.splitlines())


def test_analysis_status_is_empty_without_steps():
    assert render_analysis_status(()) == ""
