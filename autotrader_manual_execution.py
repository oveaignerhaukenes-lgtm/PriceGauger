from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from typing import Any

from autotrader_execution_context_v2 import AutoTraderExecutionContextV2, verify_execution_context_v2
from saxo_provider import SaxoInstrument
from saxo_trading import SaxoOrderRequest, SaxoTradingClient, SaxoTradingSafetyError
from trading_desk_order_preview import TradingDeskOrderPreview


MANUAL_INTENT_MAX_AGE = timedelta(minutes=5)


@dataclass(frozen=True, slots=True)
class ManualOrderIntent:
    intent_id: str
    market: str
    account_key: str
    account_id: str
    action: str
    amount: float
    instrument: SaxoInstrument
    created_at: datetime
    execution_context_v2: AutoTraderExecutionContextV2 | None = None

    def order_request(self) -> SaxoOrderRequest:
        return SaxoOrderRequest(
            account_key=self.account_key,
            instrument=self.instrument,
            amount=self.amount,
            buy_sell=self.action,
            external_reference=self.intent_id[:50],
        )


@dataclass(frozen=True, slots=True)
class ManualExecutionResult:
    intent_id: str
    order_response: dict[str, Any]
    open_orders: tuple[dict[str, Any], ...]
    net_positions: tuple[dict[str, Any], ...]

    @property
    def order_id(self) -> str | None:
        value = self.order_response.get("OrderId") or self.order_response.get("OrderIds")
        if isinstance(value, list):
            return str(value[0]) if value else None
        return str(value) if value else None


def _now_utc(now: datetime | None = None) -> datetime:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def build_manual_order_intent(
    preview: TradingDeskOrderPreview,
    *,
    execution_context_v2: AutoTraderExecutionContextV2 | None = None,
    now: datetime | None = None,
) -> ManualOrderIntent:
    created_at = _now_utc(now)
    identity_parts = [
        "manual",
        preview.market,
        preview.account_key,
        preview.action,
        f"{preview.amount:.12g}",
        str(preview.uic),
        preview.asset_type,
    ]
    if execution_context_v2 is not None:
        identity_parts.extend(("v2", execution_context_v2.fingerprint))
    identity_parts.append(created_at.isoformat())
    identity = "|".join(identity_parts)
    intent_id = "pg-" + sha256(identity.encode("utf-8")).hexdigest()[:32]
    return ManualOrderIntent(
        intent_id=intent_id,
        market=preview.market,
        account_key=preview.account_key,
        account_id=preview.account_id,
        action=preview.action,
        amount=float(preview.amount),
        instrument=SaxoInstrument(
            asset=preview.market,
            uic=preview.uic,
            asset_type=preview.asset_type,
            symbol=preview.symbol,
            description=preview.description,
        ),
        created_at=created_at,
        execution_context_v2=execution_context_v2,
    )


def validate_manual_intent(
    intent: ManualOrderIntent,
    *,
    active_account_keys: set[str],
    require_v2_context: bool = False,
    now: datetime | None = None,
) -> None:
    if intent.action not in {"Buy", "Sell"}:
        raise ValueError("manual intent action må være Buy eller Sell")
    if intent.amount <= 0:
        raise ValueError("manual intent amount må være større enn 0")
    if intent.account_key not in active_account_keys:
        raise ValueError("manual intent peker ikke på en aktiv Saxo SIM-konto")
    age = _now_utc(now) - _now_utc(intent.created_at)
    if age < timedelta(0) or age > MANUAL_INTENT_MAX_AGE:
        raise ValueError("manual order intent er stale; bygg ordren på nytt")

    if require_v2_context and intent.execution_context_v2 is None:
        raise ValueError("TradingDesk-ordre mangler eksplisitt v2 execution context")
    if intent.execution_context_v2 is not None:
        verify_execution_context_v2(intent.execution_context_v2)


def precheck_is_clear(precheck: dict[str, Any]) -> bool:
    if str(precheck.get("PreCheckResult") or "").lower() != "ok":
        return False
    return not bool(precheck.get("PreTradeDisclaimers"))


def execute_confirmed_manual_order(
    trading: SaxoTradingClient,
    intent: ManualOrderIntent,
    *,
    confirmed_intent_id: str,
    submitted_intent_ids: set[str],
) -> ManualExecutionResult:
    """Submit one explicitly confirmed manual SIM intent exactly once per caller state.

    The caller must persist `submitted_intent_ids` for the UI/session before retries.
    Once an intent id is present, this function refuses another POST even if the prior
    request ended with an uncertain network outcome. A bound v2 TradingDesk context is
    re-resolved immediately before submission so stale registry identity fails closed.
    """

    if confirmed_intent_id != intent.intent_id:
        raise SaxoTradingSafetyError("bekreftelsen gjelder ikke gjeldende ordreintent")
    if intent.intent_id in submitted_intent_ids:
        raise SaxoTradingSafetyError("denne manuelle ordren er allerede forsøkt sendt; automatisk retry er blokkert")
    if intent.execution_context_v2 is not None:
        verify_execution_context_v2(intent.execution_context_v2)

    submitted_intent_ids.add(intent.intent_id)
    order_response = trading.place_order(intent.order_request(), confirm_sim=True)
    open_orders = trading.open_orders_me(account_key=intent.account_key, uic=intent.instrument.uic)
    net_positions = trading.net_positions_me(account_id=intent.account_id, uic=intent.instrument.uic)
    return ManualExecutionResult(
        intent_id=intent.intent_id,
        order_response=order_response,
        open_orders=open_orders,
        net_positions=net_positions,
    )
