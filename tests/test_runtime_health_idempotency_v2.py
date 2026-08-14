from __future__ import annotations

from uuid import UUID

import pytest

from db_workspace_persistence_v2 import forecast_identity_v2, technical_state_identity_v2
from runtime_health_v2 import freshness_health_v2


TECHNICAL_RECIPE_ID = UUID("11111111-1111-1111-1111-111111111111")
ANALYSIS_RECIPE_ID = UUID("22222222-2222-2222-2222-222222222222")


def test_technical_state_identity_is_stable_and_semantic():
    first = technical_state_identity_v2(
        market_id=7,
        as_of="2026-08-15T00:00:00+00:00",
        technical_recipe_id=TECHNICAL_RECIPE_ID,
    )
    second = technical_state_identity_v2(
        market_id=7,
        as_of="2026-08-15T00:00:00+00:00",
        technical_recipe_id=TECHNICAL_RECIPE_ID,
    )
    changed = technical_state_identity_v2(
        market_id=8,
        as_of="2026-08-15T00:00:00+00:00",
        technical_recipe_id=TECHNICAL_RECIPE_ID,
    )

    assert first == second
    assert first != changed


def test_forecast_identity_changes_with_horizon_or_recipe():
    state_id = technical_state_identity_v2(
        market_id=7,
        as_of="2026-08-15T00:00:00+00:00",
        technical_recipe_id=TECHNICAL_RECIPE_ID,
    )
    base = forecast_identity_v2(
        market_id=7,
        as_of="2026-08-15T00:00:00+00:00",
        horizon_seconds=300,
        technical_state_id=state_id,
        analysis_recipe_id=ANALYSIS_RECIPE_ID,
    )
    longer = forecast_identity_v2(
        market_id=7,
        as_of="2026-08-15T00:00:00+00:00",
        horizon_seconds=900,
        technical_state_id=state_id,
        analysis_recipe_id=ANALYSIS_RECIPE_ID,
    )

    assert base == forecast_identity_v2(
        market_id=7,
        as_of="2026-08-15T00:00:00+00:00",
        horizon_seconds=300,
        technical_state_id=state_id,
        analysis_recipe_id=ANALYSIS_RECIPE_ID,
    )
    assert base != longer


def test_freshness_health_has_explicit_healthy_stale_and_degraded_states():
    now = "2026-08-15T00:10:00Z"

    healthy = freshness_health_v2(
        service="technical-core-v2",
        stage="producer",
        observed_at="2026-08-15T00:09:00Z",
        now=now,
        stale_after_seconds=180,
        dead_after_seconds=900,
    )
    stale = freshness_health_v2(
        service="technical-core-v2",
        stage="producer",
        observed_at="2026-08-15T00:05:00Z",
        now=now,
        stale_after_seconds=180,
        dead_after_seconds=900,
    )
    degraded = freshness_health_v2(
        service="technical-core-v2",
        stage="producer",
        observed_at="2026-08-14T23:50:00Z",
        now=now,
        stale_after_seconds=180,
        dead_after_seconds=900,
    )

    assert healthy.status == "HEALTHY"
    assert stale.status == "STALE"
    assert degraded.status == "DEGRADED"


def test_health_reports_no_data_and_rejects_invalid_thresholds():
    no_data = freshness_health_v2(
        service="technical-core-v2",
        stage="producer",
        observed_at=None,
    )
    assert no_data.status == "NO_DATA"
    assert no_data.age_seconds is None

    with pytest.raises(ValueError):
        freshness_health_v2(
            service="technical-core-v2",
            stage="producer",
            observed_at="2026-08-15T00:00:00Z",
            stale_after_seconds=300,
            dead_after_seconds=300,
        )
