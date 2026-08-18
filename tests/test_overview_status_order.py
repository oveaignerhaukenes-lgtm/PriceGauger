from __future__ import annotations

from pathlib import Path


def test_live_status_is_mounted_before_context_and_technical_overview_loading():
    source = (Path(__file__).parents[1] / "pages" / "0_Oversikt.py").read_text()

    status_mount = source.index('_fragment(run_every="2s")(_render_live_analysis_status)()')
    context_render = source.index("_render_context_v2()")
    technical_render = source.index('st.subheader("Teknisk analyse og prognose · v2")')

    assert status_mount < context_render
    assert status_mount < technical_render
    assert "AnalysisStatusStore().load()" in source
    assert "load_overview()" not in source
