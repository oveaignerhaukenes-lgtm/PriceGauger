from semantic_analogue_ranking import select_reactions_for_ranked_analogues


def test_selection_keeps_only_reactions_passing_all_similarity_thresholds():
    reactions = [
        {"candidate_event_id": "strong", "return_4h_pct": 1.2, "status": "OK"},
        {"candidate_event_id": "weak-market", "return_4h_pct": -2.0, "status": "OK"},
        {"candidate_event_id": "weak-event", "return_4h_pct": -3.0, "status": "OK"},
    ]
    rankings = [
        {
            "candidate_event_id": "strong",
            "event_similarity": 0.80,
            "market_similarity": 0.75,
            "combined_similarity": 0.775,
        },
        {
            "candidate_event_id": "weak-market",
            "event_similarity": 0.90,
            "market_similarity": 0.30,
            "combined_similarity": 0.60,
        },
        {
            "candidate_event_id": "weak-event",
            "event_similarity": 0.40,
            "market_similarity": 0.90,
            "combined_similarity": 0.65,
        },
    ]

    selection = select_reactions_for_ranked_analogues(reactions, rankings)

    assert selection.selected_event_ids == ("strong",)
    assert selection.excluded_event_ids == ("weak-market", "weak-event")
    assert selection.selected_reactions[0]["return_4h_pct"] == 1.2


def test_selection_preserves_ranking_order_and_limits_count():
    reactions = [
        {"candidate_event_id": "a", "status": "OK"},
        {"candidate_event_id": "b", "status": "OK"},
        {"candidate_event_id": "c", "status": "OK"},
    ]
    rankings = [
        {"candidate_event_id": "c", "event_similarity": 0.9, "market_similarity": 0.9, "combined_similarity": 0.9},
        {"candidate_event_id": "a", "event_similarity": 0.8, "market_similarity": 0.8, "combined_similarity": 0.8},
        {"candidate_event_id": "b", "event_similarity": 0.7, "market_similarity": 0.7, "combined_similarity": 0.7},
    ]

    selection = select_reactions_for_ranked_analogues(reactions, rankings, maximum_analogues=2)

    assert selection.selected_event_ids == ("c", "a")
    assert selection.excluded_event_ids == ("b",)
