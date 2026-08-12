from __future__ import annotations

from response_divergence import ResponseDivergenceSnapshot
from transmission_state import TransmissionStateStore, build_transmission_state


AS_OF = "2026-08-12T12:15:00+00:00"


def _support(change_by_name: dict[str, float | None]) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for name in ("Silver", "Gold", "Brent", "DXY", "US2Y", "US10Y", "US30Y"):
        change = change_by_name.get(name)
        result[name] = {
            "kind": "YIELD_PCT" if name.startswith("US") else "RETURN_PCT",
            "change": change,
            "window_coverage": "VALID" if change is not None else "MISSING",
            "latest_observation_freshness": "FRESH" if change is not None else "MISSING",
        }
    return result


def _divergence(
    *,
    status: str = "DIVERGENT",
    expected_direction: str = "UP",
    realized_direction: str = "DOWN",
    changes: dict[str, float | None] | None = None,
) -> ResponseDivergenceSnapshot:
    realized = -1.0 if realized_direction == "DOWN" else 1.0 if realized_direction == "UP" else 0.0
    return ResponseDivergenceSnapshot(
        divergence_id=f"divergence:{status}:{expected_direction}:{realized_direction}:{hash(str(changes))}",
        market="Silver",
        window="15m",
        as_of=AS_OF,
        information_snapshot_id="information:test",
        information_as_of="2026-08-12T12:00:00+00:00",
        cross_market_snapshot_id="cross:test",
        cross_market_as_of=AS_OF,
        expected_score=0.4 if expected_direction == "UP" else -0.4,
        expected_direction=expected_direction,
        realized_return_pct=realized,
        realized_direction=realized_direction,
        status=status,
        alignment_offset_seconds=0.0,
        supporting_observations=_support(changes or {}),
    )


def test_transmission_resolves_energy_inflation_only_with_macro_confirmation():
    divergence = _divergence(
        changes={
            "Silver": -1.0,
            "Gold": 0.5,
            "Brent": 2.0,
            "DXY": 0.4,
            "US2Y": None,
            "US10Y": None,
            "US30Y": None,
        }
    )

    state = build_transmission_state(divergence)

    assert state.resolution_status == "RESOLVED"
    assert state.dominant_channel == "ENERGY_INFLATION"
    assert state.channel_scores["ENERGY_INFLATION"] < 0
    assert state.channel_scores["RATES_FX"] == -0.45
    assert "US10Y" in state.evidence["ENERGY_INFLATION"]["missing_inputs"]


def test_transmission_resolves_rates_fx_when_dxy_and_yields_confirm():
    divergence = _divergence(
        changes={
            "Silver": -1.0,
            "Gold": 0.2,
            "Brent": 0.01,
            "DXY": 0.4,
            "US2Y": 0.08,
            "US10Y": 0.10,
            "US30Y": 0.12,
        }
    )

    state = build_transmission_state(divergence)

    assert state.resolution_status == "RESOLVED"
    assert state.dominant_channel == "RATES_FX"
    assert state.channel_scores["RATES_FX"] == -1.0
    assert state.evidence["RATES_FX"]["missing_inputs"] == []


def test_transmission_stays_unresolved_when_only_weak_relative_metals_signal_exists():
    divergence = _divergence(
        changes={
            "Silver": -1.0,
            "Gold": 0.5,
            "Brent": 0.0,
            "DXY": 0.0,
            "US2Y": None,
            "US10Y": None,
            "US30Y": None,
        }
    )

    state = build_transmission_state(divergence)

    assert state.resolution_status == "UNRESOLVED"
    assert state.dominant_channel is None
    assert state.channel_scores["INDUSTRIAL_GROWTH"] == -0.45
    assert "dedicated_growth_proxy" in state.evidence["INDUSTRIAL_GROWTH"]["missing_inputs"]


def test_unconfirmed_response_never_forces_a_transmission_channel():
    divergence = _divergence(
        status="UNCONFIRMED",
        realized_direction="FLAT",
        changes={
            "Silver": 0.0,
            "Gold": 0.8,
            "Brent": 2.0,
            "DXY": 0.5,
            "US2Y": 0.08,
            "US10Y": 0.10,
            "US30Y": 0.12,
        },
    )

    state = build_transmission_state(divergence)

    assert state.resolution_status == "UNRESOLVED"
    assert state.dominant_channel is None


def test_transmission_persistence_is_immutable(tmp_path):
    path = tmp_path / "transmission.db"
    state = build_transmission_state(
        _divergence(
            changes={
                "Silver": -1.0,
                "Gold": 0.5,
                "Brent": 2.0,
                "DXY": 0.4,
            }
        )
    )

    store = TransmissionStateStore(path)
    store.save(state)
    store.save(state)

    loaded = store.load_latest(market="Silver")
    assert loaded is not None
    assert loaded.to_record() == state.to_record()
