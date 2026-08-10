from analysis_status import AnalysisStatusStore
from analysis_status_ui import render_analysis_status


REUSE_DETAIL = "Ingen ny analyse nødvendig; siste tekniske state beholdes."


def _technical(store: AnalysisStatusStore):
    return next(item for item in store.load() if item.step_key == "technical_state")


def test_technical_no_change_is_reported_as_reused(tmp_path) -> None:
    store = AnalysisStatusStore(tmp_path / "status.sqlite3")
    store.begin_cycle()

    store.skipped("technical_state", REUSE_DETAIL)

    technical = _technical(store)
    assert technical.status == "REUSED"
    assert technical.detail == REUSE_DETAIL
    html = render_analysis_status((technical,))
    assert "Gjenbrukt" in html
    assert "pg-step-reused" in html


def test_real_technical_unavailability_is_not_overwritten_by_reuse(tmp_path) -> None:
    store = AnalysisStatusStore(tmp_path / "status.sqlite3")
    store.begin_cycle()
    unavailable = "Saxo-token er ikke tilgjengelig for workeren, og Twelve Data er ikke konfigurert."

    store.skipped("technical_state", unavailable)
    store.skipped("technical_state", REUSE_DETAIL)

    technical = _technical(store)
    assert technical.status == "SKIPPED"
    assert technical.detail == unavailable
    html = render_analysis_status((technical,))
    assert "Hoppet over" in html
    assert unavailable in html
