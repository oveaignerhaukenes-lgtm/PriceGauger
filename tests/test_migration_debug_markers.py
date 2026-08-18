from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_primary_surfaces_have_explicit_migration_authority() -> None:
    build_info = _source("build_info.py")
    assert '"0_Oversikt.py": (' in build_info
    overview_marker = build_info[build_info.index('"0_Oversikt.py": (') : build_info.index('"0_TradingDesk.py": (')]
    assert '"V2"' in overview_marker
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


def test_overview_v2_marker_explains_canonical_context_and_technical_sources() -> None:
    source = _source("build_info.py")
    assert "Canonical ContextSnapshotV2" in source
    assert "v2 Technical Core/workspace/forecast" in source
    assert "Ingen skjult V1 Decision/Recommendation-fallback" in source
