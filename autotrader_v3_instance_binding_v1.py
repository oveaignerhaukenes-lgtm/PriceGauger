from __future__ import annotations

from dataclasses import dataclass

from autotrader_engine_account_ownership_v1 import load_account_owner_v1
from autotrader_v3_control_plane_v1 import authority_state_v3
from autotrader_v3_instance_registry_v1 import disable_v3_instance_v1, replace_v3_instance_boundary_v1
from autotrader_v3_order_guard_v1 import pending_order
from instrument_registry_v2 import list_subscribed_sources_v2


@dataclass(frozen=True, slots=True)
class V3InstrumentBindingV1:
    market_id: int
    market_name: str
    instrument_id: int
    display_name: str
    uic: int
    asset_type: str

    @property
    def key(self) -> str:
        return f"{self.market_id}:{self.instrument_id}:{self.uic}:{self.asset_type}"

    @property
    def label(self) -> str:
        return f"{self.market_name} · {self.display_name} · UIC {self.uic} · {self.asset_type}"


def load_available_v3_instrument_bindings_v1() -> tuple[V3InstrumentBindingV1, ...]:
    """Return the same latest subscribed Saxo instrument identity used by TradingDesk."""
    grouped: dict[str, list] = {}
    for source in list_subscribed_sources_v2(provider="saxo"):
        grouped.setdefault(str(source.market_name), []).append(source)
    result: list[V3InstrumentBindingV1] = []
    for market_name, sources in grouped.items():
        source = sorted(
            sources,
            key=lambda item: (int(item.instrument_id), str(item.provider_instrument_id)),
        )[-1]
        try:
            uic = int(str(source.provider_instrument_id))
        except (TypeError, ValueError):
            continue
        asset_type = str(source.asset_type or "").strip()
        if not asset_type:
            continue
        result.append(
            V3InstrumentBindingV1(
                market_id=int(source.market_id),
                market_name=market_name,
                instrument_id=int(source.instrument_id),
                display_name=str(source.display_name),
                uic=uic,
                asset_type=asset_type,
            )
        )
    return tuple(sorted(result, key=lambda item: (item.market_name.lower(), item.instrument_id)))


def same_v3_binding_v1(instance, binding: V3InstrumentBindingV1) -> bool:
    return (
        int(instance.market_id) == int(binding.market_id)
        and int(instance.instrument_id) == int(binding.instrument_id)
        and int(instance.uic) == int(binding.uic)
        and str(instance.asset_type) == str(binding.asset_type)
    )


def remove_unarmed_v3_instance_v1(instance, *, db_path="pricegauger.db") -> None:
    """Remove an inert V3 instance from the active fleet while preserving history."""
    state = authority_state_v3(str(instance.instance_id), db_path=db_path)
    if state.live_armed or state.sim_armed:
        raise RuntimeError("Slå av både LIVE og SIM før instansen kan fjernes.")
    owner = load_account_owner_v1(str(instance.account_id), db_path=db_path)
    if owner is not None:
        raise RuntimeError(
            f"Kontoen har fortsatt execution-ownership ({owner.engine_id}/{owner.owner_key[:8]}). "
            "Frigi authority før instansen fjernes."
        )
    unresolved = pending_order(
        account_id=str(instance.account_id),
        uic=int(instance.uic),
        asset_type=str(instance.asset_type),
        db_path=db_path,
    )
    if unresolved is not None:
        raise RuntimeError("Instansen har en uavklart ordre/pending-lock.")
    disable_v3_instance_v1(instance_id=str(instance.instance_id), db_path=db_path)




def replace_unarmed_v3_instance_binding_v1(instance, binding: V3InstrumentBindingV1, *, db_path="pricegauger.db"):
    """Replace an inert instance with a new exact broker/instrument identity.

    LIVE/SIM authority, account ownership and unresolved order state all fail closed.
    The new instance starts unarmed with a fresh runtime identity.
    """
    state = authority_state_v3(str(instance.instance_id), db_path=db_path)
    if state.live_armed or state.sim_armed:
        raise RuntimeError("Slå av både LIVE og SIM før marked/instrument kan byttes.")
    owner = load_account_owner_v1(str(instance.account_id), db_path=db_path)
    if owner is not None:
        raise RuntimeError(
            f"Kontoen har fortsatt execution-ownership ({owner.engine_id}/{owner.owner_key[:8]}). "
            "Frigi authority før marked/instrument byttes."
        )
    pending = pending_order(
        account_id=str(instance.account_id),
        uic=int(instance.uic),
        asset_type=str(instance.asset_type),
        db_path=db_path,
    )
    if pending is not None:
        raise RuntimeError("Den gamle instrumenttilknytningen har en uavklart ordre/pending-lock.")
    return replace_v3_instance_boundary_v1(
        instance_id=str(instance.instance_id),
        template=binding,
        db_path=db_path,
    )


__all__ = [
    "V3InstrumentBindingV1",
    "load_available_v3_instrument_bindings_v1",
    "remove_unarmed_v3_instance_v1",
    "replace_unarmed_v3_instance_binding_v1",
    "same_v3_binding_v1",
]
