from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from trading_desk_products import LeveragedProduct, LeveragedProductDetails


@dataclass(frozen=True, slots=True)
class AutoTraderProductUniverseEntryV2:
    """One explicitly curated product identity that AutoTrader may consider.

    Saxo discovery is never authoritative for execution eligibility. An instrument
    must exist here by exact provider identity and pass the applicable hard safety
    profile. Margin products additionally require a runtime margin envelope.
    """

    uic: int
    asset_type: str
    market: str
    direction: str
    enabled: bool = False
    limited_loss_verified: bool = False
    no_margin_obligation_verified: bool = False
    transaction_costs_verified: bool = False
    margin_product_allowed: bool = False
    negative_balance_protection_verified: bool = False
    max_fixed_commission: float | None = None
    notes: str = ""

    @property
    def identity(self) -> tuple[int, str]:
        return (int(self.uic), str(self.asset_type))

    @property
    def hard_eligible(self) -> bool:
        """Static profile eligibility; margin products still need runtime envelope."""
        if not self.enabled or not self.transaction_costs_verified:
            return False
        if self.margin_product_allowed:
            return bool(self.negative_balance_protection_verified)
        return bool(self.limited_loss_verified and self.no_margin_obligation_verified)


# Fail closed by default. Products are added only after cost/risk verification.
AUTOTRADER_PRODUCT_UNIVERSE_V2: tuple[AutoTraderProductUniverseEntryV2, ...] = ()


@dataclass(frozen=True, slots=True)
class ProductEligibilityV2:
    uic: int
    asset_type: str
    market: str
    direction: str | None
    eligible: bool
    reasons: tuple[str, ...]
    entry: AutoTraderProductUniverseEntryV2 | None = None


def _entry_index(
    universe: Iterable[AutoTraderProductUniverseEntryV2] = AUTOTRADER_PRODUCT_UNIVERSE_V2,
) -> dict[tuple[int, str], AutoTraderProductUniverseEntryV2]:
    indexed: dict[tuple[int, str], AutoTraderProductUniverseEntryV2] = {}
    for entry in universe:
        identity = entry.identity
        if identity in indexed:
            raise ValueError(f"duplicate AutoTrader product identity: {identity}")
        indexed[identity] = entry
    return indexed


def evaluate_product_eligibility_v2(
    *,
    market: str,
    product: LeveragedProduct,
    details: LeveragedProductDetails | None = None,
    universe: Iterable[AutoTraderProductUniverseEntryV2] = AUTOTRADER_PRODUCT_UNIVERSE_V2,
    margin_envelope_active: bool = False,
) -> ProductEligibilityV2:
    """Return fail-closed execution eligibility for one Saxo product candidate.

    `margin_envelope_active` is deliberately false by default. A curated CFD/FX
    margin product therefore remains blocked unless the future execution caller
    explicitly proves that the deterministic margin envelope is active for that
    order path.
    """

    instrument = product.instrument
    identity = (int(instrument.uic), str(instrument.asset_type))
    entry = _entry_index(universe).get(identity)
    reasons: list[str] = []

    if entry is None:
        reasons.append("NOT_IN_PG_PRODUCT_UNIVERSE")
        return ProductEligibilityV2(
            uic=instrument.uic,
            asset_type=instrument.asset_type,
            market=market,
            direction=product.direction,
            eligible=False,
            reasons=tuple(reasons),
            entry=None,
        )

    if entry.market != market:
        reasons.append("MARKET_MISMATCH")
    observed_direction = (details.direction if details is not None else product.direction) or product.direction
    configured_direction = str(entry.direction or "").strip().lower()
    if (
        observed_direction
        and configured_direction not in {"both", "either"}
        and configured_direction != str(observed_direction).lower()
    ):
        reasons.append("DIRECTION_MISMATCH")
    if not entry.enabled:
        reasons.append("DISABLED")

    if entry.margin_product_allowed:
        if not entry.negative_balance_protection_verified:
            reasons.append("NEGATIVE_BALANCE_PROTECTION_NOT_VERIFIED")
        if not margin_envelope_active:
            reasons.append("MARGIN_ENVELOPE_NOT_ACTIVE")
    else:
        if not entry.limited_loss_verified:
            reasons.append("LIMITED_LOSS_NOT_VERIFIED")
        if not entry.no_margin_obligation_verified:
            reasons.append("NO_MARGIN_OBLIGATION_NOT_VERIFIED")

    if not entry.transaction_costs_verified:
        reasons.append("TRANSACTION_COSTS_NOT_VERIFIED")
    if details is not None and details.is_tradable is False:
        reasons.append("NOT_TRADABLE")

    return ProductEligibilityV2(
        uic=instrument.uic,
        asset_type=instrument.asset_type,
        market=market,
        direction=observed_direction,
        eligible=not reasons,
        reasons=tuple(reasons),
        entry=entry,
    )


def require_product_eligible_v2(
    *,
    market: str,
    product: LeveragedProduct,
    details: LeveragedProductDetails | None = None,
    universe: Iterable[AutoTraderProductUniverseEntryV2] = AUTOTRADER_PRODUCT_UNIVERSE_V2,
    margin_envelope_active: bool = False,
) -> AutoTraderProductUniverseEntryV2:
    result = evaluate_product_eligibility_v2(
        market=market,
        product=product,
        details=details,
        universe=universe,
        margin_envelope_active=margin_envelope_active,
    )
    if not result.eligible or result.entry is None:
        reason = ", ".join(result.reasons) or "UNKNOWN"
        raise ValueError(
            f"produkt {result.uic}/{result.asset_type} er ikke AutoTrader-eligible: {reason}"
        )
    return result.entry
