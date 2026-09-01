from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any


_EPSILON = 1e-12


@dataclass(frozen=True, slots=True)
class NetPositionExposureV2:
    direction: str
    amount: float
    source: str


def _number(value: Any, *, field: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"Saxo net position has invalid {field}: {value!r}") from exc
    if result < -_EPSILON:
        raise RuntimeError(f"Saxo net position has negative {field}: {result}")
    return max(0.0, result)


def resolve_net_position_exposure_v2(
    base: dict[str, Any],
    *,
    net_position_id: str,
    logger: logging.Logger | None = None,
) -> NetPositionExposureV2 | None:
    """Resolve net exposure without trusting OpeningDirection alone.

    Saxo explicitly exposes AmountLong and AmountShort on NetPositionStatic. When
    those fields are present they are the primary authority for direction and net
    amount. OpeningDirection is retained as a compatibility fallback for older or
    reduced payloads and as a cross-check only.

    Ambiguous/squared exposure fails closed instead of guessing. Raising here is
    deliberate: every execution path consumes the same position adapter, so a bad
    direction cannot be mistaken for FLAT or be turned into an opposite CLOSE order.
    """
    log = logger or logging.getLogger("pricegauger.autotrader.saxo_net_position_direction_v2")
    opening = str(base.get("OpeningDirection") or "").strip().title()
    if opening not in {"", "Buy", "Sell"}:
        raise RuntimeError(
            f"Saxo net position {net_position_id} has unsupported OpeningDirection={opening!r}"
        )

    raw_amount = float(base.get("Amount") or 0.0)
    has_long = "AmountLong" in base and base.get("AmountLong") is not None
    has_short = "AmountShort" in base and base.get("AmountShort") is not None

    if has_long or has_short:
        amount_long = _number(base.get("AmountLong") or 0.0, field="AmountLong")
        amount_short = _number(base.get("AmountShort") or 0.0, field="AmountShort")
        net = amount_long - amount_short

        if abs(net) <= _EPSILON:
            if amount_long > _EPSILON or amount_short > _EPSILON:
                raise RuntimeError(
                    "Saxo net position direction is ambiguous/squared "
                    f"id={net_position_id} AmountLong={amount_long} AmountShort={amount_short}"
                )
            if abs(raw_amount) > _EPSILON:
                raise RuntimeError(
                    "Saxo net position direction fields contradict Amount "
                    f"id={net_position_id} Amount={raw_amount} AmountLong={amount_long} "
                    f"AmountShort={amount_short}"
                )
            return None

        direction = "Buy" if net > 0 else "Sell"
        amount = abs(net)
        if amount_long > _EPSILON and amount_short > _EPSILON:
            log.warning(
                "Saxo net position contains mixed long/short exposure id=%s uic=%s "
                "Amount=%s AmountLong=%s AmountShort=%s resolved=%s amount=%s",
                net_position_id,
                base.get("Uic"),
                raw_amount,
                amount_long,
                amount_short,
                direction,
                amount,
            )
        if opening and opening != direction:
            log.warning(
                "Saxo net-position direction disagreement id=%s uic=%s OpeningDirection=%s "
                "Amount=%s AmountLong=%s AmountShort=%s resolved=%s amount=%s",
                net_position_id,
                base.get("Uic"),
                opening,
                raw_amount,
                amount_long,
                amount_short,
                direction,
                amount,
            )
        if abs(abs(raw_amount) - amount) > max(_EPSILON, amount * 1e-9):
            log.warning(
                "Saxo net-position amount disagreement id=%s uic=%s Amount=%s "
                "AmountLong=%s AmountShort=%s resolved_amount=%s",
                net_position_id,
                base.get("Uic"),
                raw_amount,
                amount_long,
                amount_short,
                amount,
            )
        return NetPositionExposureV2(direction=direction, amount=amount, source="AMOUNT_LONG_SHORT")

    if abs(raw_amount) <= _EPSILON:
        return None
    if not opening:
        # Saxo's NetPositionStatic.Amount is documented as volume, not as a signed
        # direction authority. Without either OpeningDirection or explicit long/short
        # totals it is unsafe to infer a trading side from Amount's sign.
        raise RuntimeError(
            f"Saxo net position {net_position_id} lacks direction authority for Amount={raw_amount}"
        )
    return NetPositionExposureV2(
        direction=opening,
        amount=abs(raw_amount),
        source="OPENING_DIRECTION_FALLBACK",
    )


__all__ = ["NetPositionExposureV2", "resolve_net_position_exposure_v2"]
