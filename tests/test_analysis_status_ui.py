from __future__ import annotations

from analysis_status import AnalysisStepStatus
from analysis_status_ui import ANALYSIS_STATUS_CSS, render_analysis_status


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
                status="RUNNING",
                detail="Henter prisbarer",
                updated_at="2026-08-01T00:12:01+00:00",
            ),
            AnalysisStepStatus(
                step_key="decision_state",
                label="Decision State",
                status="FAILED",
                detail="Kunne ikke lese markedsdata",
                updated_at="2026-08-01T00:12:02+00:00",
            ),
        )
    )

    assert "Analyseflyt" in html
    assert "Telegram innhentet" in html
    assert "Teknisk analyse" in html
    assert "Ferdig" in html
    assert "Arbeider" in html
    assert "pg-step-running" in html
    assert "Feilet" in html
    assert "pg-step-failed" in html
    assert "×" in html
    assert "12 poster hentet" in html
    assert "Kunne ikke lese markedsdata" in html


def test_analysis_status_is_empty_without_steps():
    assert render_analysis_status(()) == ""


def test_running_animation_rotates_only_the_spinner_glyph():
    running_rule = ".pg-step-running .pg-step-icon::before"
    assert running_rule in ANALYSIS_STATUS_CSS
    assert "animation:pg-spin" in ANALYSIS_STATUS_CSS
    assert "opacity" not in ANALYSIS_STATUS_CSS.split(running_rule, 1)[1].split("}", 1)[0]
