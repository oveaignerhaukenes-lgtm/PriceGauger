from __future__ import annotations

from pathlib import Path
from typing import Iterable


def persist_finished_signals(
    *,
    database_path: str | Path,
    reactions: Iterable[object],
    window_hours: int = 24,
    half_life_hours: float = 6.0,
    minimum_similarity: float = 0.20,
) -> int:
    """Compatibility boundary retained for older storage callers.

    GDELT reactions are historical evidence, not primary market events. They must
    therefore never be converted directly into EventSignal rows. The event-centric
    pipeline creates and stores one canonical signal per Telegram event after the
    GDELT candidates have been ranked and combined into a market profile.
    """
    del database_path, reactions, window_hours, half_life_hours, minimum_similarity
    return 0
