from historical_engine import build_historical_assessment


def _row(event_id: str, published_at: str, value: float, *, status: str = "OK") -> dict:
    return {
        "candidate_event_id": event_id,
        "published_at": published_at,
        "return_15m_pct": value / 4,
        "return_1h_pct": value / 2,
        "return_4h_pct": value,
        "return_24h_pct": value * 2,
        "status": status,
    }


def test_historical_engine_deduplicates_publication_times_and_builds_forecast():
    reactions = [
        _row("a", "2026-07-01T10:00:00+00:00", 1.0),
        _row("b", "2026-07-01T10:00:00+00:00", 1.0),
        _row("c", "2026-07-02T10:00:00+00:00", 2.0),
        _row("d", "2026-07-03T10:00:00+00:00", -0.5),
        _row("e", "2026-07-04T10:00:00+00:00", 1.5),
        _row("f", "2026-07-05T10:00:00+00:00", 0.5),
    ]

    result = build_historical_assessment(reactions, source_search_id="search-1")

    assert result.raw_reactions == 6
    assert result.duplicate_reactions_removed == 1
    assert result.independent_analogues == 5
    assert result.forecast_direction == "UP"
    assert result.probability_up == 0.8
    assert result.expected_return_pct == 1.0
    assert result.status == "PROVISIONAL_UNRANKED"
    assert result.calibration_target == "realized_return_4h_pct"
    assert result.assessment_id.startswith("historical-assessment:")


def test_historical_engine_reports_insufficient_data_without_valid_prices():
    result = build_historical_assessment(
        [_row("a", "", 1.0, status="TIMESTAMP_MISSING")],
        source_search_id="search-2",
    )

    assert result.status == "INSUFFICIENT_DATA"
    assert result.forecast_direction == "INSUFFICIENT_DATA"
    assert result.probability_up is None
    assert result.confidence == 0.0
    assert result.independent_analogues == 0
