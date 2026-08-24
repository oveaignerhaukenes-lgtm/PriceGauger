from __future__ import annotations

import autotrader_risk_control_v2 as risk


def _observation(*, position_id: str = "NP1", amount: float = 1.0) -> risk.PositionObservationV2:
    return risk.PositionObservationV2(
        account_id="A1",
        net_position_id=position_id,
        uic=42,
        asset_type="CfdOnIndex",
        direction="Buy",
        amount=amount,
        average_open_price=100.0,
        current_price=99.0,
        pnl_pct=-1.0,
        price_delay_minutes=0,
        can_be_closed=True,
        calculation_reliability="Ok",
        is_market_open=True,
        non_tradable_reason="None",
    )


def _enrollment(*, position_id: str = "NP1", amount: float = 1.0) -> dict[str, object]:
    return {
        "account_id": "A1",
        "net_position_id": position_id,
        "uic": 42,
        "asset_type": "CfdOnIndex",
        "direction": "Buy",
        "amount": amount,
        "average_open_price": 100.0,
        "managed": True,
    }


def test_canonical_cadences_are_ten_and_two_seconds() -> None:
    assert risk.DEFAULT_PORTFOLIO_OBSERVATION_SECONDS == 10
    assert risk.DEFAULT_MANAGED_RISK_REACTION_SECONDS == 2


def test_fast_reaction_makes_no_saxo_call_without_active_enrollment(monkeypatch) -> None:
    monkeypatch.setattr(risk, "load_active_managed_positions_v1", lambda: ())

    def forbidden():
        raise AssertionError("Saxo client must not be resolved without Auto-manage enrollment")

    monkeypatch.setattr(risk, "configured_client", forbidden)
    summary = risk.run_managed_risk_reaction_cycle_v2()
    assert summary == risk.RiskCycleSummaryV2(observed=0, close_signals=0, failed=0)


def test_fast_reaction_evaluates_only_exact_enrollment(monkeypatch) -> None:
    enrolled = _enrollment()
    exact = _observation()
    resized = _observation(position_id="NP2", amount=2.0)
    monkeypatch.setattr(risk, "load_active_managed_positions_v1", lambda: (enrolled,))
    monkeypatch.setattr(risk, "configured_client", lambda: object())
    monkeypatch.setattr(risk, "_position_observations_v2", lambda client: (exact, resized))
    monkeypatch.setattr(risk, "load_risk_config_v2", risk.RiskConfigV2)

    captured: dict[str, object] = {}

    def evaluate(observations, *, config, deactivate_missing):
        captured["observations"] = observations
        captured["deactivate_missing"] = deactivate_missing
        return risk.RiskCycleSummaryV2(
            observed=len(observations),
            close_signals=0,
            failed=0,
        )

    monkeypatch.setattr(risk, "_evaluate_observations_v2", evaluate)
    summary = risk.run_managed_risk_reaction_cycle_v2()

    assert captured["observations"] == (exact,)
    assert captured["deactivate_missing"] is False
    assert summary.observed == 1


def test_fast_reaction_rejects_changed_position_basis(monkeypatch) -> None:
    monkeypatch.setattr(risk, "load_active_managed_positions_v1", lambda: (_enrollment(),))
    monkeypatch.setattr(risk, "configured_client", lambda: object())
    monkeypatch.setattr(
        risk,
        "_position_observations_v2",
        lambda client: (_observation(amount=2.0),),
    )
    monkeypatch.setattr(risk, "load_risk_config_v2", risk.RiskConfigV2)

    captured: dict[str, object] = {}

    def evaluate(observations, *, config, deactivate_missing):
        captured["observations"] = observations
        return risk.RiskCycleSummaryV2(
            observed=len(observations),
            close_signals=0,
            failed=0,
        )

    monkeypatch.setattr(risk, "_evaluate_observations_v2", evaluate)
    summary = risk.run_managed_risk_reaction_cycle_v2()

    assert captured["observations"] == ()
    assert summary.observed == 0
