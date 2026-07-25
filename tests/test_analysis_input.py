from analysis_input import AnalysisInput, _fallback, canonical_event_from_input


def test_search_request_is_not_recast_as_event():
    value = AnalysisInput(
        input_id="manual-1",
        input_type="SEARCH_REQUEST",
        source="MANUAL",
        raw_text="Find recent developments around Hormuz and analyse Brent",
    )
    interpretation = _fallback(value, "SEARCH_REQUEST")
    assert interpretation.input_type == "SEARCH_REQUEST"
    assert "Brent" in interpretation.affected_assets


def test_scenario_remains_scenario_in_canonical_preview():
    value = AnalysisInput(
        input_id="manual-2",
        input_type="SCENARIO",
        source="MANUAL",
        raw_text="What happens to gold if a ceasefire is announced?",
    )
    interpretation = _fallback(value, "SCENARIO")
    canonical = canonical_event_from_input(value, interpretation)
    assert interpretation.input_type == "SCENARIO"
    assert canonical.source_message_id == "manual-2"
    assert canonical.event_id.startswith("manual:")
