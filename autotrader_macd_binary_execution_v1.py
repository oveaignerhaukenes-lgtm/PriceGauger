from __future__ import annotations

from functools import lru_cache

from autotrader_entry_sizing_policy_v2 import (
    SIZING_MODE_MAX,
    load_entry_sizing_policy_v2,
    save_entry_sizing_policy_v2,
)
from autotrader_strategy_enrollment_v2 import StrategyEnrollmentV2
from saxo_provider import SaxoClient


SIMPLE_BINARY_MACD_STRATEGIES_V1 = frozenset(
    {
        "macd-1m-flip-control-shadow-v1",
        "macd-2m-flip-control-shadow-v1",
        "macd-5m-flip-control-shadow-v1",
        "macd-15m-flip-control-shadow-v1",
        "macd-30m-long-short-v1",
        "macd2-10-v1",
        "macd2-s-v1",
        "macd-a-v1",
    }
)


def is_simple_binary_macd_strategy_v1(strategy_key: str) -> bool:
    return str(strategy_key) in SIMPLE_BINARY_MACD_STRATEGIES_V1


@lru_cache(maxsize=16)
def _account_key_v1(client_identity: int, account_id: str, client: SaxoClient) -> str:
    payload = client._get("port/v1/accounts/me")
    rows = payload.get("Data") or []
    if not isinstance(rows, list):
        raise RuntimeError("Saxo account list had invalid format")
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("AccountId") or "") != str(account_id):
            continue
        key = str(row.get("AccountKey") or "").strip()
        if key:
            return key
    raise RuntimeError("could not resolve AccountKey for binary MACD sizing")


def ensure_binary_macd_max_sizing_v1(
    enrollment: StrategyEnrollmentV2,
    client: SaxoClient,
) -> bool:
    """Force simple MACD benchmarks to use MAX_WITHIN_PILOT in both directions.

    This changes only the existing sizing policy. Saxo precheck and the pilot Margin
    Envelope remain the final authority for the actual amount.
    """
    if not is_simple_binary_macd_strategy_v1(enrollment.strategy_key):
        return False
    account_key = _account_key_v1(id(client), str(enrollment.account_id), client)
    changed = False
    for direction in ("LONG", "SHORT"):
        policy = load_entry_sizing_policy_v2(
            account_key=account_key,
            uic=int(enrollment.uic),
            asset_type=str(enrollment.asset_type),
            direction=direction,
        )
        if policy.sizing_mode != SIZING_MODE_MAX:
            save_entry_sizing_policy_v2(
                account_key=account_key,
                uic=int(enrollment.uic),
                asset_type=str(enrollment.asset_type),
                direction=direction,
                sizing_mode=SIZING_MODE_MAX,
            )
            changed = True
    return changed


__all__ = [
    "SIMPLE_BINARY_MACD_STRATEGIES_V1",
    "ensure_binary_macd_max_sizing_v1",
    "is_simple_binary_macd_strategy_v1",
]
