from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class V2PrecheckBlockV1:
    category: str
    code: str
    detail: str

    @property
    def message(self) -> str:
        return f"{self.category}:{self.code}" + (f" · {self.detail}" if self.detail else "")


def _fmt(value: Any) -> str:
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return "?"


def classify_precheck_block_v1(item: Any, *, max_notional_account: float | None = None) -> V2PrecheckBlockV1 | None:
    """Return the exact non-secret reason an entry candidate cannot execute.

    This is deliberately read-only and engine-specific. It never changes authority,
    sizing, margin policy or Saxo payloads; it only makes the existing decision visible.
    """
    if item is None:
        return V2PrecheckBlockV1("PRECHECK", "NO_RESULT", "Saxo/precheck did not produce a usable result")

    result = str(getattr(item, "precheck_result", "") or "").strip()
    if result.lower() != "ok":
        return V2PrecheckBlockV1("SAXO_PRECHECK", result or "UNKNOWN", "Saxo did not approve the candidate")

    if bool(getattr(item, "disclaimers_present", False)):
        return V2PrecheckBlockV1("SAXO_PRECHECK", "DISCLAIMERS", "Saxo requires a pre-trade disclaimer")

    decision = getattr(item, "margin_decision", None)
    if decision is not None and not bool(getattr(decision, "allowed", False)):
        reasons = tuple(str(value) for value in (getattr(decision, "reasons", ()) or ()))
        code = ",".join(reasons) or "UNKNOWN"
        leverage = getattr(decision, "effective_leverage", None)
        detail = (
            f"notional={_fmt(getattr(item, 'notional_account', None))}; "
            f"initial_margin={_fmt(getattr(item, 'initial_margin_account', None))}; "
            f"available_after={_fmt(getattr(item, 'available_margin_after_account', None))}; "
            f"effective_leverage={_fmt(leverage)}"
        )
        return V2PrecheckBlockV1("MARGIN_ENVELOPE", code, detail)

    notional = getattr(item, "notional_account", None)
    if max_notional_account is not None and notional is not None and float(notional) > float(max_notional_account) + 1e-8:
        return V2PrecheckBlockV1(
            "SIZING",
            "NOTIONAL_CAP",
            f"candidate={_fmt(notional)}; cap={_fmt(max_notional_account)}",
        )

    return None


def classify_precheck_exception_v1(exc: Exception) -> V2PrecheckBlockV1:
    status = str(getattr(exc, "status", "") or "").strip()
    if status:
        return V2PrecheckBlockV1("SAXO", status, str(exc))
    return V2PrecheckBlockV1("SIZING", type(exc).__name__.upper(), str(exc))


__all__ = [
    "V2PrecheckBlockV1",
    "classify_precheck_block_v1",
    "classify_precheck_exception_v1",
]
