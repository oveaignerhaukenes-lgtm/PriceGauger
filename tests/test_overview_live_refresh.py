from analysis_status_ui import ANALYSIS_STATUS_CSS


def test_periodic_fragment_refresh_does_not_dim_existing_cards():
    assert '[data-stale="true"] {opacity:1 !important;}' in ANALYSIS_STATUS_CSS
