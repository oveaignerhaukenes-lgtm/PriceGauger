from openai_companion_provider import _normalize_scenario_paths


def test_normalize_scenario_paths_repairs_duplicate_progress_without_changing_returns():
    record = {
        "scenarios": [
            {
                "scenario_id": "base",
                "path_profile": [
                    {"progress": 0.0, "cumulative_return": 0.0},
                    {"progress": 0.4, "cumulative_return": 0.002},
                    {"progress": 0.4, "cumulative_return": -0.001},
                    {"progress": 1.0, "cumulative_return": 0.004},
                ],
            }
        ]
    }

    normalized = _normalize_scenario_paths(record)
    points = normalized["scenarios"][0]["path_profile"]

    assert [point["progress"] for point in points] == [0.0, 1 / 3, 2 / 3, 1.0]
    assert [point["cumulative_return"] for point in points] == [0.0, 0.002, -0.001, 0.004]


def test_normalize_scenario_paths_does_not_mutate_input():
    record = {
        "scenarios": [
            {
                "scenario_id": "base",
                "path_profile": [
                    {"progress": 0.0, "cumulative_return": 0.0},
                    {"progress": 0.2, "cumulative_return": 0.001},
                    {"progress": 0.8, "cumulative_return": 0.002},
                    {"progress": 1.0, "cumulative_return": 0.003},
                ],
            }
        ]
    }

    _normalize_scenario_paths(record)

    assert [point["progress"] for point in record["scenarios"][0]["path_profile"]] == [0.0, 0.2, 0.8, 1.0]
