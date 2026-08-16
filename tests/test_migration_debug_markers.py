from __future__ import annotations

from pathlib import Path


def test_temporary_migration_markers_cover_primary_surfaces() -> None:
    root = Path(__file__).resolve().parents[1]
    expected = {
        "pages/0_Oversikt.py": 'render_migration_badge("MIXED"',
        "pages/0_TradingDesk.py": 'render_migration_badge("V2"',
        "pages/9_V2_Technical.py": 'render_migration_badge("V2"',
        "pages/4_Telegram_Flow.py": 'render_migration_badge("LEGACY/V1"',
        "pages/3_News_Context.py": 'render_migration_badge("LEGACY/V1"',
    }
    for path, marker in expected.items():
        assert marker in (root / path).read_text(encoding="utf-8")


def test_overview_marks_legacy_sections_not_v2_forecast() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (root / "pages/0_Oversikt.py").read_text(encoding="utf-8")
    assert "render_legacy_source_note" in source
    assert "Teknisk analyse og prognose · v2" in source
