"""AutoTrader V4 is an isolated, no-order-authority architecture prototype.

Nothing here imports the legacy LIVE runtime or Saxo order POST adapter.
A separate service must be explicitly built/authorized before broker trading.
"""

from .domain import (
    BboObservation,
    IntentState,
    SaxoBoundary,
    StrategyRef,
    TradeDecision,
    advance_intent_state,
)

__all__ = [
    "BboObservation",
    "IntentState",
    "SaxoBoundary",
    "StrategyRef",
    "TradeDecision",
    "advance_intent_state",
]
