from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Iterable


MIN_COMPARISON_GROUP = 5


@dataclass(frozen=True, slots=True)
class AdaptationDiagnosticSummary:
    total_count: int
    context_count: int
    divergence_count: int
    nondivergence_count: int
    unresolved_count: int
    resolved_count: int
    median_abs_error_all: float | None
    median_abs_error_divergence: float | None
    median_abs_error_nondivergence: float | None
    median_abs_error_unresolved: float | None
    median_abs_error_resolved: float | None
    min_group_size: int = MIN_COMPARISON_GROUP

    @property
    def divergence_comparison_ready(self) -> bool:
        return self.divergence_count >= self.min_group_size and self.nondivergence_count >= self.min_group_size

    @property
    def transmission_comparison_ready(self) -> bool:
        return self.unresolved_count >= self.min_group_size and self.resolved_count >= self.min_group_size

    @property
    def divergence_error_delta(self) -> float | None:
        if not self.divergence_comparison_ready:
            return None
        assert self.median_abs_error_divergence is not None
        assert self.median_abs_error_nondivergence is not None
        return self.median_abs_error_divergence - self.median_abs_error_nondivergence

    @property
    def transmission_error_delta(self) -> float | None:
        if not self.transmission_comparison_ready:
            return None
        assert self.median_abs_error_unresolved is not None
        assert self.median_abs_error_resolved is not None
        return self.median_abs_error_unresolved - self.median_abs_error_resolved


def _median(values: list[float]) -> float | None:
    return None if not values else float(median(values))


def summarize_adaptation_diagnostics(observations: Iterable[object]) -> AdaptationDiagnosticSummary:
    """Compare absolute forecast error across already-observed context groups.

    This is descriptive only. It does not perform significance testing, infer
    causality, persist a score or feed any learning/forecast weight.
    """
    all_errors: list[float] = []
    divergence: list[float] = []
    nondivergence: list[float] = []
    unresolved: list[float] = []
    resolved: list[float] = []
    context_count = 0

    for item in observations:
        value = getattr(item, "normalized_center_error", None)
        if value is None:
            continue
        absolute = abs(float(value))
        all_errors.append(absolute)
        context = getattr(item, "adaptation_context", None)
        if context is None or not context.has_context:
            continue
        context_count += 1
        if context.saw_divergence:
            divergence.append(absolute)
        else:
            nondivergence.append(absolute)
        if context.transmission_count:
            if context.saw_unresolved_transmission:
                unresolved.append(absolute)
            elif context.resolved_count > 0:
                resolved.append(absolute)

    return AdaptationDiagnosticSummary(
        total_count=len(all_errors),
        context_count=context_count,
        divergence_count=len(divergence),
        nondivergence_count=len(nondivergence),
        unresolved_count=len(unresolved),
        resolved_count=len(resolved),
        median_abs_error_all=_median(all_errors),
        median_abs_error_divergence=_median(divergence),
        median_abs_error_nondivergence=_median(nondivergence),
        median_abs_error_unresolved=_median(unresolved),
        median_abs_error_resolved=_median(resolved),
    )
