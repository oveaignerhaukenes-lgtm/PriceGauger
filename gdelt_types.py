from __future__ import annotations

from dataclasses import dataclass

from event_models import MarketEvent


class GdeltError(RuntimeError):
    """Safe, user-displayable GDELT failure with no credentials or full request URL."""

    def __init__(self, message: str, *, stage: str, status_code: int | None = None) -> None:
        self.stage = stage
        self.status_code = status_code
        prefix = stage
        if status_code is not None:
            prefix += f" · HTTP {status_code}"
        super().__init__(f"{prefix}: {message}")


@dataclass(slots=True)
class GdeltPage:
    events: list[MarketEvent]
    next_cursor: str | None
    warning: str | None = None
