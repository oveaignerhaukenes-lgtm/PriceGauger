from __future__ import annotations

from dataclasses import dataclass

from instrument_registry_v2 import InstrumentSourceV2, resolve_instrument_source_v2


@dataclass(frozen=True, slots=True)
class AutoTraderExecutionContextV2:
    """Authoritative TradingDesk v2 identity carried into manual execution.

    This identifies the canonical market/feed instrument that authorized the
    TradingDesk trade surface. It does not replace the separately selected Saxo
    execution product (for example a Mini/KO product).
    """

    market_id: int
    market_name: str
    instrument_id: int
    provider: str
    provider_instrument_id: str
    asset_type: str | None

    @classmethod
    def from_source(
        cls,
        *,
        market_id: int,
        market_name: str,
        source: InstrumentSourceV2,
    ) -> "AutoTraderExecutionContextV2":
        if int(source.market_id) != int(market_id):
            raise ValueError("v2 source market_id matcher ikke TradingDesk-context")
        if source.market_name != market_name:
            raise ValueError("v2 source market_name matcher ikke TradingDesk-context")
        return cls(
            market_id=int(market_id),
            market_name=str(market_name),
            instrument_id=int(source.instrument_id),
            provider=str(source.provider).strip().lower(),
            provider_instrument_id=str(source.provider_instrument_id).strip(),
            asset_type=str(source.asset_type) if source.asset_type else None,
        )

    @property
    def fingerprint(self) -> str:
        return "|".join(
            (
                str(self.market_id),
                self.market_name,
                str(self.instrument_id),
                self.provider,
                self.provider_instrument_id,
                self.asset_type or "",
            )
        )


def verify_execution_context_v2(context: AutoTraderExecutionContextV2) -> InstrumentSourceV2:
    """Re-resolve the canonical source and fail closed on stale/mismatched identity."""

    if context.market_id <= 0 or context.instrument_id <= 0:
        raise ValueError("v2 execution context mangler gyldig market_id/instrument_id")
    if not context.market_name.strip():
        raise ValueError("v2 execution context mangler market_name")
    if context.provider != "saxo":
        raise ValueError("AutoTrader manual SIM execution krever Saxo v2 provider source")
    if not context.provider_instrument_id:
        raise ValueError("v2 execution context mangler provider_instrument_id")

    resolved = resolve_instrument_source_v2(
        provider=context.provider,
        provider_instrument_id=context.provider_instrument_id,
        require_subscription=True,
    )

    mismatches: list[str] = []
    if int(resolved.market_id) != int(context.market_id):
        mismatches.append("market_id")
    if resolved.market_name != context.market_name:
        mismatches.append("market_name")
    if int(resolved.instrument_id) != int(context.instrument_id):
        mismatches.append("instrument_id")
    if str(resolved.provider).strip().lower() != context.provider:
        mismatches.append("provider")
    if str(resolved.provider_instrument_id) != context.provider_instrument_id:
        mismatches.append("provider_instrument_id")
    resolved_asset_type = str(resolved.asset_type) if resolved.asset_type else None
    if resolved_asset_type != context.asset_type:
        mismatches.append("asset_type")

    if mismatches:
        raise ValueError(
            "v2 execution context er stale eller mismatchende: " + ", ".join(mismatches)
        )
    return resolved
