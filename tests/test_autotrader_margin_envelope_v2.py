from autotrader_margin_envelope_v2 import (
    AutoTraderMarginEnvelopeV2,
    AutoTraderMarginProposalV2,
    AutoTraderMarginStateV2,
    evaluate_margin_envelope_v2,
)


def _envelope(**overrides):
    values = {
        "currency": "NOK",
        "capital_control_limit": 1000.0,
        "max_initial_margin": 400.0,
        "max_notional_exposure": 2000.0,
        "max_effective_leverage": 2.0,
        "minimum_free_capital": 400.0,
        "enabled": True,
    }
    values.update(overrides)
    return AutoTraderMarginEnvelopeV2(**values)


def _state():
    return AutoTraderMarginStateV2(
        currency="NOK",
        controlled_capital=200.0,
        initial_margin_used=100.0,
        gross_notional_exposure=300.0,
        free_capital=900.0,
    )


def test_safe_resulting_exposure_is_allowed():
    decision = evaluate_margin_envelope_v2(
        _envelope(),
        _state(),
        AutoTraderMarginProposalV2(
            currency="NOK",
            resulting_controlled_capital=600.0,
            resulting_initial_margin=250.0,
            resulting_gross_notional=1000.0,
            resulting_free_capital=700.0,
            estimated_transaction_cost=0.5,
        ),
    )

    assert decision.allowed is True
    assert decision.reasons == ()
    assert decision.effective_leverage == 1000.0 / 600.0


def test_envelope_fails_closed_when_precheck_values_are_unknown():
    decision = evaluate_margin_envelope_v2(
        _envelope(),
        _state(),
        AutoTraderMarginProposalV2(
            currency="NOK",
            resulting_controlled_capital=600.0,
            resulting_initial_margin=None,
            resulting_gross_notional=1000.0,
            resulting_free_capital=700.0,
        ),
    )

    assert decision.allowed is False
    assert "UNKNOWN_PRECHECK_VALUE:resulting_initial_margin" in decision.reasons
    assert decision.effective_leverage is None


def test_margin_notional_leverage_and_free_buffer_are_independent_hard_limits():
    decision = evaluate_margin_envelope_v2(
        _envelope(),
        _state(),
        AutoTraderMarginProposalV2(
            currency="NOK",
            resulting_controlled_capital=800.0,
            resulting_initial_margin=450.0,
            resulting_gross_notional=2200.0,
            resulting_free_capital=350.0,
        ),
    )

    assert decision.allowed is False
    assert "INITIAL_MARGIN_LIMIT" in decision.reasons
    assert "NOTIONAL_LIMIT" in decision.reasons
    assert "FREE_CAPITAL_BUFFER" in decision.reasons
    assert "EFFECTIVE_LEVERAGE_LIMIT" in decision.reasons


def test_strategy_cannot_bypass_capital_control_limit_with_low_margin():
    decision = evaluate_margin_envelope_v2(
        _envelope(max_initial_margin=900.0, max_notional_exposure=5000.0, max_effective_leverage=5.0),
        _state(),
        AutoTraderMarginProposalV2(
            currency="NOK",
            resulting_controlled_capital=1200.0,
            resulting_initial_margin=200.0,
            resulting_gross_notional=1800.0,
            resulting_free_capital=800.0,
        ),
    )

    assert decision.allowed is False
    assert "CAPITAL_CONTROL_LIMIT" in decision.reasons


def test_disabled_envelope_never_allows_open_or_add():
    decision = evaluate_margin_envelope_v2(
        _envelope(enabled=False),
        _state(),
        AutoTraderMarginProposalV2(
            currency="NOK",
            resulting_controlled_capital=100.0,
            resulting_initial_margin=50.0,
            resulting_gross_notional=100.0,
            resulting_free_capital=950.0,
        ),
    )

    assert decision.allowed is False
    assert "MARGIN_ENVELOPE_DISABLED" in decision.reasons
