from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class PrecheckFailureDiagnosticsV1:
    block_reason: str
    result: str
    error_code: str
    error_message: str
    has_disclaimers: bool
    response_keys: tuple[str, ...]


def _clean(value: Any, *, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit]


def precheck_failure_diagnostics_v1(precheck: dict[str, Any]) -> PrecheckFailureDiagnosticsV1:
    """Extract non-secret diagnostics from a Saxo order precheck failure.

    Saxo returns HTTP 200 for both successful and failed prechecks. On failure the
    useful reason lives in ErrorInfo, while PreCheckResult is only ``Error``.
    Keep the persisted block reason compact and deliberately avoid serialising the
    full response, AccountKey, ExternalReference, disclaimer tokens, or payload.
    """
    result = _clean(precheck.get("PreCheckResult") or "PRECHECK_BLOCKED", limit=64)
    error_info = precheck.get("ErrorInfo")
    if not isinstance(error_info, dict):
        error_info = {}
    error_code = _clean(error_info.get("ErrorCode"), limit=128)
    error_message = _clean(error_info.get("Message"), limit=320)
    has_disclaimers = bool(precheck.get("PreTradeDisclaimers"))

    parts = [result]
    if error_code:
        parts.append(error_code)
    if error_message:
        parts.append(error_message)
    if has_disclaimers:
        parts.append("DISCLAIMERS")
    block_reason = ":".join(parts)[:500]

    return PrecheckFailureDiagnosticsV1(
        block_reason=block_reason,
        result=result,
        error_code=error_code,
        error_message=error_message,
        has_disclaimers=has_disclaimers,
        response_keys=tuple(sorted(str(key) for key in precheck.keys())),
    )


__all__ = ["PrecheckFailureDiagnosticsV1", "precheck_failure_diagnostics_v1"]
