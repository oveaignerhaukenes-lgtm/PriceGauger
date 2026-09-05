from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Mapping


@dataclass(frozen=True, slots=True)
class SpringContextInputV1:
    """Neutral adapter contract for optional external Spring evidence.

    Examples include Telegram/news, Technical Core, CrossMarketState, positioning and
    liquidity models. Inputs can influence a later model layer, but cannot execute trades.
    """

    source_key: str
    observed_at: datetime
    market_id: int | None = None
    instrument_id: int | None = None
    equilibrium_prior_return_pct: float | None = None
    shock_prior_score: float | None = None
    confidence: float | None = None
    ttl_seconds: int | None = None
    features: Mapping[str, float | str | bool] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.source_key.strip():
            raise ValueError("source_key must be non-empty")
        if self.confidence is not None and not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError("confidence must be within [0, 1]")
        if self.ttl_seconds is not None and int(self.ttl_seconds) <= 0:
            raise ValueError("ttl_seconds must be positive")


__all__ = ["SpringContextInputV1"]
