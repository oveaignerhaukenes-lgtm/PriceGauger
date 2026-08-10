from pathlib import Path


def test_market_detail_controls_render_in_sidebar() -> None:
    source = Path("market_detail_controls.py").read_text(encoding="utf-8")

    assert "sidebar = st.sidebar" in source
    assert 'sidebar.selectbox("Marked"' in source
    assert 'sidebar.caption("Tidsoppløsning")' in source
    assert "resolution_columns = sidebar.columns" in source
    assert 'sidebar.toggle(\n        "Vis tidligere prognosespor"' in source
    assert "sidebar.checkbox(" in source


def test_market_view_keeps_card_market_query_param_and_faded_trails() -> None:
    source = Path("pages/7_Forecast_Learning.py").read_text(encoding="utf-8")

    assert 'st.query_params.get("market")' in source
    assert 'st.query_params["market"] = market' in source
    assert "ghost_forecast_opacities" in source
    assert "fade_path_segments" in source
    assert 'name="Tidligere prognoser"' in source
