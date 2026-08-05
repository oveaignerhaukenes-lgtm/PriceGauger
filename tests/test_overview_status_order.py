from __future__ import annotations

from pathlib import Path


def test_live_status_is_mounted_before_overview_and_summary_loading():
    source = (Path(__file__).parents[1] / "pages" / "0_Oversikt.py").read_text()

    status_mount = source.index('_fragment(run_every="2s")(_render_live_analysis_status)()')
    overview_load = source.index("data = load_overview()")
    summary_load = source.index("build_overview_summary(data)")

    assert status_mount < overview_load
    assert status_mount < summary_load
    assert "AnalysisStatusStore().load()" in source
    assert "live_data = load_overview()" not in source
