from analyst_companion_v2 import CompanionAnalysisV2
from companion_runtime_v2 import CompanionSessionV2


def _analysis(as_of: str, direction: str) -> CompanionAnalysisV2:
    return CompanionAnalysisV2(
        market="Gold",
        as_of=as_of,
        recipe_version="test",
        directional_context=direction,
        breakout_status="NONE",
        pullback_type="NONE",
        squeeze_risk="LOW",
        watched_support_ids=(),
        watched_resistance_ids=(),
        confidence=0.5,
        what_changed="",
        commentary=f"{direction} test",
        watch_conditions=(),
        scenarios=(),
    )


def test_companion_session_keeps_last_ten_analyses_in_chronological_order():
    session = CompanionSessionV2.activate("Gold")
    for index in range(12):
        session.append_analysis(_analysis(f"2026-08-25T{index:02d}:00:00+00:00", "BULLISH"))
    assert len(session.analysis_history) == 10
    assert session.analysis_history[0].as_of == "2026-08-25T02:00:00+00:00"
    assert session.analysis_history[-1].as_of == "2026-08-25T11:00:00+00:00"


def test_companion_session_replaces_same_timestamp_analysis_instead_of_duplicate_card():
    session = CompanionSessionV2.activate("Gold")
    session.append_analysis(_analysis("2026-08-25T10:00:00+00:00", "BULLISH"))
    session.append_analysis(_analysis("2026-08-25T10:00:00+00:00", "BEARISH"))
    assert len(session.analysis_history) == 1
    assert session.analysis_history[0].directional_context == "BEARISH"
