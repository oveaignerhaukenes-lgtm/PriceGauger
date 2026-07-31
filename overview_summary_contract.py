from __future__ import annotations

from dataclasses import asdict, dataclass


SUMMARY_ENGINE_VERSION = "overview-summary-v1"
SENSITIVITY_TYPES = (
    "HEADLINE_SENSITIVE",
    "COMMODITY_SENSITIVE",
    "MACRO_POLICY_SENSITIVE",
    "MIXED",
    "UNCLEAR",
)


@dataclass(frozen=True, slots=True)
class OverviewSummary:
    regime: str
    sensitivity: str
    headline: str
    summary: str
    key_driver: str
    caveat: str
    model: str
    engine_version: str = SUMMARY_ENGINE_VERSION

    def to_record(self) -> dict:
        return asdict(self)
