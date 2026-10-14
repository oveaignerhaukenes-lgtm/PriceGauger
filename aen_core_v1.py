"""AEn Core v1: broker-free, causal structure and inventory target state machine.

This module has no Saxo, DB, network, or worker imports. It is SIM research code.
A swing at candle i is only known after right confirmation candles have closed.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal, Sequence

Side = Literal["LONG", "SHORT", "HOLD"]
Action = Literal["HOLD", "OPEN", "ADD", "REDUCE", "FLAT"]


@dataclass(frozen=True)
class AEnConfig:
    signal_tf_minutes: int = 5
    structure_tf_minutes: int = 5
    pivot_left: int = 2
    pivot_right: int = 2
    max_units: int = 1
    unit_lots: float = 0.01

    def __post_init__(self):
        if self.signal_tf_minutes not in (1, 2, 5, 10, 15, 30):
            raise ValueError("unsupported signal timeframe")
        if self.structure_tf_minutes not in (1, 2, 5, 10, 15, 30):
            raise ValueError("unsupported structure timeframe")
        if self.pivot_left < 1 or self.pivot_right < 1:
            raise ValueError("pivot confirmation must have at least one bar on each side")
        if self.max_units < 1 or self.unit_lots <= 0:
            raise ValueError("invalid unit cap or quantity")


@dataclass(frozen=True)
class Bar:
    timestamp: str
    high: float
    low: float
    close: float

    def __post_init__(self):
        if not (self.low <= self.close <= self.high):
            raise ValueError("invalid OHLC bar")


@dataclass(frozen=True)
class StructureEvent:
    kind: Literal["HH", "HL", "LL", "LH"]
    pivot_index: int
    known_index: int
    level: float


@dataclass(frozen=True)
class Inventory:
    side: Side = "HOLD"
    units: int = 0
    structure_break: bool = False
    last_add_event: int = -1

    def __post_init__(self):
        if self.units < 0 or (self.side == "HOLD") != (self.units == 0):
            raise ValueError("invalid inventory")


@dataclass(frozen=True)
class Decision:
    action: Action
    target: Inventory
    reason: str


def confirmed_structure_events(bars: Sequence[Bar], cfg: AEnConfig) -> tuple[StructureEvent, ...]:
    """Events are emitted ONLY at known_index; equal highs/lows do not create pivots."""
    output: list[StructureEvent] = []
    prior_high = prior_low = None
    for i in range(cfg.pivot_left, len(bars) - cfg.pivot_right):
        window = bars[i - cfg.pivot_left:i + cfg.pivot_right + 1]
        center = bars[i]
        is_high = center.high == max(b.high for b in window) and sum(b.high == center.high for b in window) == 1
        is_low = center.low == min(b.low for b in window) and sum(b.low == center.low for b in window) == 1
        known = i + cfg.pivot_right
        if is_high:
            if prior_high is not None and center.high != prior_high:
                output.append(StructureEvent("HH" if center.high > prior_high else "LH", i, known, center.high))
            prior_high = center.high
        if is_low:
            if prior_low is not None and center.low != prior_low:
                output.append(StructureEvent("HL" if center.low > prior_low else "LL", i, known, center.low))
            prior_low = center.low
    return tuple(sorted(output, key=lambda e: (e.known_index, e.pivot_index, e.kind)))


def evaluate_structure(inventory: Inventory, *, event: StructureEvent,
                       cfg: AEnConfig, regime: Side, protected_level_broken: bool = False) -> Decision:
    """One deterministic target decision per confirmed event, never a broker action.

    A position is opened only on HL in LONG regime or LH in SHORT regime;
    reversal first requests HOLD, never directly submits the opposite side.
    Caller must persist last processed event and verify actual broker flat outside this module.
    """
    if inventory.units > cfg.max_units:
        target_units = cfg.max_units
        return Decision("REDUCE", replace(inventory, units=target_units),
                        "user reduced hard cap")
    if protected_level_broken and inventory.side != "HOLD":
        if inventory.units > 1:
            return Decision("REDUCE", replace(inventory, units=inventory.units - 1, structure_break=True),
                            "protected swing broken")
        return Decision("FLAT", Inventory(), "protected swing broken at minimum size")
    if inventory.side == "LONG" and inventory.structure_break and event.kind == "LH":
        return Decision("FLAT", Inventory(), "confirmed lower high after bullish structure break")
    if inventory.side == "SHORT" and inventory.structure_break and event.kind == "HL":
        return Decision("FLAT", Inventory(), "confirmed higher low after bearish structure break")
    if inventory.side != "HOLD" and inventory.side != regime:
        return Decision("FLAT", Inventory(), "opposite signal requires verified flat before entry")
    if inventory.side == "HOLD":
        if event.kind == "HL" and regime == "LONG":
            return Decision("OPEN", Inventory("LONG", 1, False, event.known_index), "confirmed higher low")
        if event.kind == "LH" and regime == "SHORT":
            return Decision("OPEN", Inventory("SHORT", 1, False, event.known_index), "confirmed lower high")
    if inventory.side == "LONG" and regime == "LONG" and event.kind == "HL" and not inventory.structure_break:
        if event.known_index > inventory.last_add_event and inventory.units < cfg.max_units:
            return Decision("ADD", replace(inventory, units=inventory.units + 1,
                                           last_add_event=event.known_index), "confirmed higher low")
    if inventory.side == "SHORT" and regime == "SHORT" and event.kind == "LH" and not inventory.structure_break:
        if event.known_index > inventory.last_add_event and inventory.units < cfg.max_units:
            return Decision("ADD", replace(inventory, units=inventory.units + 1,
                                           last_add_event=event.known_index), "confirmed lower high")
    return Decision("HOLD", inventory, "no authorized structural change")


def change_timeframe(current: int, proposed: int, *, can_switch: bool) -> int:
    """Changing resolution never changes inventory and cannot emit orders."""
    if proposed not in (1, 2, 5, 10, 15, 30):
        raise ValueError("unsupported timeframe")
    return proposed if can_switch else current
