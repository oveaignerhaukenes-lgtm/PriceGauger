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
from market_chat_panel import render_market_chat_panel


ENGINE_LABELS = {
    ENGINE_NEWS_CONTEXT: "Nyhetskontekst / informasjon",
    ENGINE_HISTORICAL: "Historisk motor",
    ENGINE_TECHNICAL: "Teknisk analyse",
}

RESOLUTION_LABELS = {
    "AUTO": "Auto",
    "1m": "1",
    "5m": "5",
    "15m": "15",
    "1t": "1t",
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


def render_market_detail_controls(
    st,
    *,
    markets: list[str],
    initial_market: str,
    resolution_choices,
    store=None,
    container=None,
):
    """Render persisted Markedsvisning controls and market chat.

    ``container`` is a presentation surface only. Markedsvisning supplies its right
    workspace column; callers that omit it retain the historical sidebar fallback.
    Runtime/forecast semantics remain owned by the analysis layer rather than UI.
    """
    preference_store = store or AnalysisViewPreferenceStore()
    panel = container or st.sidebar
    panel.markdown("### Arbeidsflate")
    market = panel.selectbox("Marked", markets, index=markets.index(initial_market))

    saved = preference_store.load(market)
    resolution_key = f"market-detail-resolution-{market}"
    if resolution_key not in st.session_state:
        st.session_state[resolution_key] = (
            saved.resolution if saved.resolution in resolution_choices else resolution_choices[0]
        )

    panel.caption("Tidsoppløsning")
    resolution_columns = panel.columns(len(resolution_choices))
    for column, choice in zip(resolution_columns, resolution_choices):
        if column.button(
            RESOLUTION_LABELS.get(choice, str(choice)),
            key=f"market-detail-resolution-button-{market}-{choice}",
            type="primary" if st.session_state[resolution_key] == choice else "secondary",
            use_container_width=True,
        ):
            st.session_state[resolution_key] = choice
    resolution = st.session_state[resolution_key]

    show_learning = panel.toggle(
        "Vis tidligere prognosespor",
        value=saved.show_learning,
        key=f"market-detail-learning-{market}",
        help="Viser tidligere lagrede forecasts som gradvis uttonede spor bak gjeldende prognose.",
    )

    panel.markdown("**Motorer i analysevisningen**")
    enabled: list[str] = []
    for engine in ANALYSIS_ENGINES:
        active = panel.checkbox(
            ENGINE_LABELS[engine],
            value=saved.enabled(engine),
            key=f"market-detail-engine-{market}-{engine}",
        )
        if active:
            enabled.append(engine)

    with panel.expander("Om grafen", expanded=False):
        panel.caption(
            "Markedsvisning bruker lagret worker-data. Auto velger oppløsning etter forecast-horisonten; "
            "manuelt valg kan ikke skape finere data enn det som faktisk er lagret."
        )

    updated = AnalysisViewPreferences(
        market=market,
        enabled_engines=tuple(enabled),
        resolution=resolution,
        show_learning=show_learning,
    )
    if updated != saved:
        preference_store.save(updated)

    panel.divider()
    render_market_chat_panel(st, market=market, container=panel)
    return market, resolution, show_learning, updated.enabled_engines
