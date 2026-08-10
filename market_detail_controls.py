from __future__ import annotations

from dataclasses import replace

from analysis_view_preferences import (
    ANALYSIS_ENGINES,
    ENGINE_HISTORICAL,
    ENGINE_NEWS_CONTEXT,
    ENGINE_TECHNICAL,
    AnalysisViewPreferenceStore,
    AnalysisViewPreferences,
)


ENGINE_LABELS = {
    ENGINE_NEWS_CONTEXT: "Nyhetskontekst / informasjon",
    ENGINE_HISTORICAL: "Historisk motor",
    ENGINE_TECHNICAL: "Teknisk analyse",
}


def update_preferences(
    current: AnalysisViewPreferences,
    *,
    enabled_engines: tuple[str, ...] | list[str] | None = None,
    resolution: str | None = None,
    show_learning: bool | None = None,
) -> AnalysisViewPreferences:
    return replace(
        current,
        enabled_engines=current.enabled_engines if enabled_engines is None else tuple(enabled_engines),
        resolution=current.resolution if resolution is None else str(resolution),
        show_learning=current.show_learning if show_learning is None else bool(show_learning),
    )


def render_market_detail_controls(st, *, markets: list[str], initial_market: str, resolution_choices, store=None):
    """Render persisted controls for the enlarged market card.

    The controls own presentation preferences only. Runtime/forecast semantics are
    deliberately supplied by the analysis layer rather than mutated by Streamlit.
    """
    preference_store = store or AnalysisViewPreferenceStore()
    control_market, control_resolution, control_learning = st.columns([2.2, 3.2, 2.2])
    with control_market:
        market = st.selectbox("Marked", markets, index=markets.index(initial_market))

    saved = preference_store.load(market)
    resolution_index = (
        list(resolution_choices).index(saved.resolution)
        if saved.resolution in resolution_choices
        else 0
    )
    with control_resolution:
        resolution = st.radio(
            "Tidsoppløsning",
            resolution_choices,
            horizontal=True,
            index=resolution_index,
            key=f"market-detail-resolution-{market}",
        )
    with control_learning:
        show_learning = st.toggle(
            "Vis læring / gamle forecasts",
            value=saved.show_learning,
            key=f"market-detail-learning-{market}",
        )

    st.markdown("**Motorer i analysevisningen**")
    engine_columns = st.columns(len(ANALYSIS_ENGINES))
    enabled: list[str] = []
    for column, engine in zip(engine_columns, ANALYSIS_ENGINES):
        with column:
            active = st.checkbox(
                ENGINE_LABELS[engine],
                value=saved.enabled(engine),
                key=f"market-detail-engine-{market}-{engine}",
            )
        if active:
            enabled.append(engine)

    updated = AnalysisViewPreferences(
        market=market,
        enabled_engines=tuple(enabled),
        resolution=resolution,
        show_learning=show_learning,
    )
    if updated != saved:
        preference_store.save(updated)
    return market, resolution, show_learning, updated.enabled_engines
