from analysis_view_preferences import (
    ANALYSIS_ENGINES,
    ENGINE_HISTORICAL,
    ENGINE_NEWS_CONTEXT,
    AnalysisViewPreferenceStore,
    AnalysisViewPreferences,
)
from market_detail_controls import update_preferences


def test_defaults_enable_all_engines_and_persist_per_market(tmp_path) -> None:
    store = AnalysisViewPreferenceStore(tmp_path / "pg.db")

    gold = store.load("Gold")
    assert gold.enabled_engines == ANALYSIS_ENGINES
    assert gold.resolution == "AUTO"
    assert gold.show_learning is True

    changed = AnalysisViewPreferences(
        market="Gold",
        enabled_engines=(ENGINE_NEWS_CONTEXT, ENGINE_HISTORICAL),
        resolution="5m",
        show_learning=False,
    )
    store.save(changed)

    assert store.load("Gold") == changed
    assert store.load("Brent").enabled_engines == ANALYSIS_ENGINES


def test_unknown_engines_are_discarded_in_stable_order() -> None:
    preferences = AnalysisViewPreferences(
        market="Silver",
        enabled_engines=("unknown", ENGINE_HISTORICAL, ENGINE_NEWS_CONTEXT),
    )

    assert preferences.enabled_engines == (ENGINE_NEWS_CONTEXT, ENGINE_HISTORICAL)


def test_update_preferences_only_changes_requested_fields() -> None:
    current = AnalysisViewPreferences(market="Brent")

    changed = update_preferences(
        current,
        enabled_engines=(ENGINE_HISTORICAL,),
        show_learning=False,
    )

    assert changed.market == "Brent"
    assert changed.enabled_engines == (ENGINE_HISTORICAL,)
    assert changed.resolution == "AUTO"
    assert changed.show_learning is False
