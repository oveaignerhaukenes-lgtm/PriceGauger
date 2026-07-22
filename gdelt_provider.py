from __future__ import annotations

from dataclasses import dataclass

from gdelt_client import GdeltClient
from gdelt_direct_client import DirectGdeltClient


@dataclass(frozen=True, slots=True)
class GdeltProviderConfig:
    name: str = "direct"
    cloud_api_key: str = ""
    timeout: int = 30


def build_gdelt_client(config: GdeltProviderConfig):
    provider = config.name.strip().lower() or "direct"
    if provider == "direct":
        return DirectGdeltClient(timeout=config.timeout)
    if provider == "cloud":
        if not config.cloud_api_key.strip():
            raise ValueError("GDELT_PROVIDER=cloud krever GDELT_CLOUD_API_KEY")
        return GdeltClient(config.cloud_api_key, timeout=config.timeout)
    if provider == "auto":
        if config.cloud_api_key.strip():
            return GdeltClient(config.cloud_api_key, timeout=config.timeout)
        return DirectGdeltClient(timeout=config.timeout)
    raise ValueError("GDELT_PROVIDER må være direct, cloud eller auto")
