from __future__ import annotations

from dataclasses import asdict, dataclass


PROTOCOL_VERSION = "paper-test-v1"


@dataclass(frozen=True, slots=True)
class TestProtocol:
    """Locked rules for the first prospective PriceGauger paper test."""

    version: str = PROTOCOL_VERSION
    assets: tuple[str, ...] = ("Brent", "Gold", "Silver", "DXY")
    directions: tuple[str, ...] = ("LONG", "SHORT", "NEUTRAL")
    entry_rule: str = "first available 5-minute close at or after signal timestamp"
    evaluation_hours: tuple[int, ...] = (1, 4)
    excursion_window_hours: int = 4
    bar_interval_minutes: int = 5
    minimum_signal_strength: int = 0
    execution_mode: str = "paper/manual"
    model_changes_during_test: bool = False
    price_provider_changes_during_test: bool = False

    def to_record(self) -> dict:
        return asdict(self)


PAPER_TEST_PROTOCOL = TestProtocol()


def directional_return(return_pct: float | None, direction: str) -> float | None:
    """Return performance from the recommendation's point of view."""
    if return_pct is None or direction == "NEUTRAL":
        return None
    return -return_pct if direction == "SHORT" else return_pct


def is_directional_hit(return_pct: float | None, direction: str) -> bool | None:
    value = directional_return(return_pct, direction)
    return None if value is None else value > 0
