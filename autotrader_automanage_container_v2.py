from __future__ import annotations

from dataclasses import dataclass
from uuid import NAMESPACE_URL, uuid5

from autotrader_risk_control_v2 import PositionObservationV2
from instrument_registry_v2 import resolve_instrument_source_v2


@dataclass(frozen=True, slots=True)
class AutoManageProductV2:
    """One exact provider product bound to canonical market/history identity.

    This is intentionally strategy-neutral. Strategies are attached as independent
    pilots on top of the same product container, so one product can be compared
    across several policies without hard-coding a specific UIC or AssetType.
    """

    provider: str
    account_id: str
    anchor_position_id: str
    provider_instrument_id: str
    asset_type: str
    market_id: int
    market_name: str
    instrument_id: int

    def __post_init__(self) -> None:
        if not self.provider.strip():
            raise ValueError("provider is required")
        if not self.account_id.strip():
            raise ValueError("account_id is required")
        if not self.provider_instrument_id.strip():
            raise ValueError("provider_instrument_id is required")
        if not self.asset_type.strip():
            raise ValueError("asset_type is required")
        if int(self.market_id) <= 0 or int(self.instrument_id) <= 0:
            raise ValueError("canonical market_id/instrument_id are required")
        if not self.market_name.strip():
            raise ValueError("market_name is required")

    @property
    def product_key(self) -> str:
        identity = "|".join(
            (
                self.provider.lower(),
                self.account_id,
                self.provider_instrument_id,
                self.asset_type,
            )
        )
        return str(uuid5(NAMESPACE_URL, identity))

    def pilot_key(self, strategy_key: str) -> str:
        strategy = str(strategy_key or "").strip()
        if not strategy:
            raise ValueError("strategy_key is required")
        # Preserve the existing Saxo flip key shape so an already-created first
        # pilot remains stable while strategy becomes an explicit dimension.
        if self.provider.lower() == "saxo":
            identity = f"{strategy}|{self.account_id}|{self.provider_instrument_id}|{self.asset_type}"
        else:
            identity = f"{strategy}|{self.provider.lower()}|{self.account_id}|{self.provider_instrument_id}|{self.asset_type}"
        return str(uuid5(NAMESPACE_URL, identity))

    @property
    def source_fingerprint(self) -> str:
        return "|".join(
            (
                self.provider.lower(),
                self.provider_instrument_id,
                self.asset_type,
                str(self.instrument_id),
                str(self.market_id),
                self.market_name,
            )
        )


def resolve_saxo_automanage_product_v2(observation: PositionObservationV2) -> AutoManageProductV2:
    """Resolve any subscribed Saxo product into the generic AutoManage container."""
    source = resolve_instrument_source_v2(
        provider="saxo",
        provider_instrument_id=str(int(observation.uic)),
        require_subscription=True,
    )
    resolved_asset_type = str(source.asset_type or "").strip()
    observed_asset_type = str(observation.asset_type or "").strip()
    if not resolved_asset_type or resolved_asset_type != observed_asset_type:
        raise ValueError(
            "Saxo product resolved to a different canonical AssetType; refusing ambiguous AutoManage binding"
        )
    return AutoManageProductV2(
        provider="saxo",
        account_id=str(observation.account_id).strip(),
        anchor_position_id=str(observation.net_position_id or "").strip(),
        provider_instrument_id=str(int(observation.uic)),
        asset_type=observed_asset_type,
        market_id=int(source.market_id),
        market_name=source.market_name,
        instrument_id=int(source.instrument_id),
    )


__all__ = ["AutoManageProductV2", "resolve_saxo_automanage_product_v2"]
