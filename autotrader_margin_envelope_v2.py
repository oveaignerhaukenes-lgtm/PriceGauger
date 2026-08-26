from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AutoTraderMarginEnvelopeV2:
    """Hard execution limits outside strategy/AI authority.

    The strategy may request exposure, but these limits define the maximum position
    the execution layer may ever create or add to. They are deliberately expressed
    as absolute monetary/notional ceilings rather than inferred from a model signal.
    """

    currency: str
    capital_control_limit: float
    max_initial_margin: float
    max_notional_exposure: float
    max_effective_leverage: float
    minimum_free_capital: float = 0.0
    enabled: bool = False

    def __post_init__(self) -> None:
        if not str(self.currency).strip():
            raise ValueError("currency is required")
        if float(self.capital_control_limit) <= 0:
            raise ValueError("capital_control_limit must be positive")
        if float(self.max_initial_margin) <= 0:
            raise ValueError("max_initial_margin must be positive")
        if float(self.max_notional_exposure) <= 0:
            raise ValueError("max_notional_exposure must be positive")
        if float(self.max_effective_leverage) <= 0:
            raise ValueError("max_effective_leverage must be positive")
        if float(self.minimum_free_capital) < 0:
            raise ValueError("minimum_free_capital cannot be negative")
        if float(self.minimum_free_capital) >= float(self.capital_control_limit):
            raise ValueError("minimum_free_capital must be smaller than capital_control_limit")


@dataclass(frozen=True, slots=True)
class AutoTraderMarginStateV2:
    """Observed account/execution state before a proposed OPEN/ADD."""

    currency: str
    controlled_capital: float
    initial_margin_used: float
    gross_notional_exposure: float
    free_capital: float

    def __post_init__(self) -> None:
        for name in (
            "controlled_capital",
            "initial_margin_used",
            "gross_notional_exposure",
            "free_capital",
        ):
            if float(getattr(self, name)) < 0:
                raise ValueError(f"{name} cannot be negative")


@dataclass(frozen=True, slots=True)
class AutoTraderMarginProposalV2:
    """Resulting state if one proposed execution action were accepted."""

    currency: str
    resulting_controlled_capital: float | None
    resulting_initial_margin: float | None
    resulting_gross_notional: float | None
    resulting_free_capital: float | None
    estimated_transaction_cost: float | None = None
    source: str = "saxo-precheck"


@dataclass(frozen=True, slots=True)
class AutoTraderMarginDecisionV2:
    allowed: bool
    reasons: tuple[str, ...]
    effective_leverage: float | None


_REQUIRED_UNKNOWN = "UNKNOWN_PRECHECK_VALUE"


def evaluate_margin_envelope_v2(
    envelope: AutoTraderMarginEnvelopeV2,
    state: AutoTraderMarginStateV2,
    proposal: AutoTraderMarginProposalV2,
) -> AutoTraderMarginDecisionV2:
    """Fail-closed evaluation of one proposed resulting exposure.

    The execution layer should evaluate the *resulting* state after every OPEN/ADD.
    REDUCE/CLOSE may later use a separate reduce-only path so a risk-reducing action
    is never blocked merely because the account is already outside an entry limit.
    """

    reasons: list[str] = []
    if not envelope.enabled:
        reasons.append("MARGIN_ENVELOPE_DISABLED")

    expected_currency = envelope.currency.upper()
    if state.currency.upper() != expected_currency or proposal.currency.upper() != expected_currency:
        reasons.append("CURRENCY_MISMATCH")

    required_values = {
        "resulting_controlled_capital": proposal.resulting_controlled_capital,
        "resulting_initial_margin": proposal.resulting_initial_margin,
        "resulting_gross_notional": proposal.resulting_gross_notional,
        "resulting_free_capital": proposal.resulting_free_capital,
    }
    for name, value in required_values.items():
        if value is None:
            reasons.append(f"{_REQUIRED_UNKNOWN}:{name}")
        elif float(value) < 0:
            reasons.append(f"NEGATIVE_VALUE:{name}")

    if reasons and any(reason.startswith(_REQUIRED_UNKNOWN) for reason in reasons):
        return AutoTraderMarginDecisionV2(False, tuple(reasons), None)

    controlled = float(proposal.resulting_controlled_capital or 0.0)
    margin = float(proposal.resulting_initial_margin or 0.0)
    notional = float(proposal.resulting_gross_notional or 0.0)
    free_capital = float(proposal.resulting_free_capital or 0.0)

    if controlled > float(envelope.capital_control_limit) + 1e-9:
        reasons.append("CAPITAL_CONTROL_LIMIT")
    if margin > float(envelope.max_initial_margin) + 1e-9:
        reasons.append("INITIAL_MARGIN_LIMIT")
    if notional > float(envelope.max_notional_exposure) + 1e-9:
        reasons.append("NOTIONAL_LIMIT")
    if free_capital + 1e-9 < float(envelope.minimum_free_capital):
        reasons.append("FREE_CAPITAL_BUFFER")

    effective_leverage = None
    if controlled > 0:
        effective_leverage = notional / controlled
        if effective_leverage > float(envelope.max_effective_leverage) + 1e-9:
            reasons.append("EFFECTIVE_LEVERAGE_LIMIT")
    elif notional > 0:
        reasons.append("NOTIONAL_WITHOUT_CONTROLLED_CAPITAL")

    if proposal.estimated_transaction_cost is not None and float(proposal.estimated_transaction_cost) < 0:
        reasons.append("NEGATIVE_TRANSACTION_COST")

    return AutoTraderMarginDecisionV2(
        allowed=not reasons,
        reasons=tuple(reasons),
        effective_leverage=effective_leverage,
    )
