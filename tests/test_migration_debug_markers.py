from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_primary_surfaces_have_explicit_migration_authority() -> None:
    build_info = _source("build_info.py")
    assert '"0_Oversikt.py": (' in build_info
    assert '"MIXED"' in build_info
    assert '"0_TradingDesk.py": (' in build_info
    assert '"6_AutoTrader_POC.py": (' in build_info

    v2_technical = _source("pages/9_V2_Technical.py")
    assert 'render_migration_badge("V2")' in v2_technical


def test_engine_sidebar_marks_remaining_engine_surfaces_legacy() -> None:
    source = _source("engine_sidebar.py")
    assert 'render_migration_badge(' in source
    assert '"LEGACY/V1"' in source
    assert '"news"' in source
    assert '"telegram_flow"' in source
    assert "migration pending" in source


def test_overview_mixed_marker_explains_v2_and_legacy_split() -> None:
    source = _source("build_info.py")
    assert "V2: markedskort/Technical Core/forecast" in source
    assert "Legacy/V1: nyhets-, Telegram- og Information State-kontekst" in source
