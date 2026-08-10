from pathlib import Path


def test_market_detail_controls_support_workspace_container() -> None:
    source = Path("market_detail_controls.py").read_text(encoding="utf-8")

    assert "container=None" in source
    assert "panel = container or st.sidebar" in source
    assert 'panel.selectbox("Marked"' in source
    assert 'panel.caption("Tidsoppløsning")' in source
    assert "resolution_columns = panel.columns" in source
    assert 'panel.toggle(\n        "Vis tidligere prognosespor"' in source
    assert "panel.checkbox(" in source
    assert "render_market_chat_panel(st, market=market, container=panel)" in source


def test_market_view_uses_right_workspace_and_keeps_forecast_controls() -> None:
    source = Path("pages/7_Forecast_Learning.py").read_text(encoding="utf-8")

    assert "analysis_column, workspace_column = st.columns([2.35, 1.0]" in source
    assert "container=workspace_column" in source
    assert "with analysis_column:" in source
    assert 'st.query_params.get("market")' in source
    assert 'st.query_params["market"] = market' in source
    assert "ghost_forecast_opacities" in source
    assert "fade_path_segments" in source
    assert 'name="Tidligere prognoser"' in source
