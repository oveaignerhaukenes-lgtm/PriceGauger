from __future__ import annotations

from dataclasses import dataclass

from trading_desk_products import LeveragedProduct


@dataclass(frozen=True, slots=True)
class TradingDeskOrderPreview:
    market: str
    account_key: str
    account_id: str
    action: str
    amount: float
    product_direction: str | None
    uic: int
    asset_type: str
    symbol: str
    description: str

    @property
    def action_label(self) -> str:
        return "KJØP" if self.action == "Buy" else "SELG"

    @property
    def exposure_label(self) -> str:
        if self.action == "Buy" and self.product_direction in {"Long", "Short"}:
            return f"Kjøp av et {self.product_direction}-produkt"
        if self.action == "Sell":
            return "Salg av valgt produkt; posisjonseffekt avhenger av eksisterende beholdning"
        return "Eksponering ikke entydig oppgitt av Saxo"


def build_order_preview(
    *,
    market: str,
    product: LeveragedProduct,
    account_key: str,
    account_id: str,
    action: str,
    amount: float,
) -> TradingDeskOrderPreview:
    normalized_action = action.strip().title()
    if normalized_action not in {"Buy", "Sell"}:
        raise ValueError("action må være Buy eller Sell")

    normalized_amount = float(amount)
    if normalized_amount <= 0:
        raise ValueError("amount må være større enn 0")
    if not account_key.strip():
        raise ValueError("account_key mangler")

    instrument = product.instrument
    return TradingDeskOrderPreview(
        market=market,
        account_key=account_key,
        account_id=account_id,
        action=normalized_action,
        amount=normalized_amount,
        product_direction=product.direction,
        uic=instrument.uic,
        asset_type=instrument.asset_type,
        symbol=instrument.symbol,
        description=instrument.description,
    )
