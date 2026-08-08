from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests

from saxo_provider import SIM_BASE_URL, SaxoClient, SaxoError, SaxoInstrument, configured_client


class SaxoTradingSafetyError(RuntimeError):
    """Raised when the proof-of-concept trading guardrails are not satisfied."""


@dataclass(frozen=True, slots=True)
class SaxoAccount:
    account_key: str
    account_id: str
    currency: str
    active: bool


@dataclass(frozen=True, slots=True)
class SaxoOrderRequest:
    account_key: str
    instrument: SaxoInstrument
    amount: float
    buy_sell: str

    def payload(self) -> dict[str, Any]:
        side = self.buy_sell.strip().title()
        if side not in {"Buy", "Sell"}:
            raise ValueError("buy_sell må være Buy eller Sell")
        amount = float(self.amount)
        if amount <= 0:
            raise ValueError("amount må være større enn 0")
        if not self.account_key.strip():
            raise ValueError("account_key mangler")
        return {
            "AccountKey": self.account_key,
            "Amount": amount,
            "AssetType": self.instrument.asset_type,
            "BuySell": side,
            "ManualOrder": True,
            "OrderDuration": {"DurationType": "DayOrder"},
            "OrderType": "Market",
            "Uic": self.instrument.uic,
        }


class SaxoTradingClient:
    """Deliberately SIM-only trading adapter for the AutoTrader proof of concept.

    This class is intentionally not connected to PriceGauger analysis or the worker.
    Live trading is rejected in code, and order placement requires an explicit
    confirmation argument in addition to the UI confirmation.
    """

    def __init__(self, client: SaxoClient) -> None:
        self.client = client
        normalized = self.client.base_url.rstrip("/").lower()
        if normalized != SIM_BASE_URL.lower():
            raise SaxoTradingSafetyError(
                "AutoTrader POC er låst til Saxo SIM og nekter å bruke LIVE-endepunkt."
            )

    def accounts(self) -> tuple[SaxoAccount, ...]:
        payload = self.client._get("port/v1/accounts/me")
        rows = payload.get("Data") or []
        if not isinstance(rows, list):
            raise SaxoError("kontolisten hadde ugyldig format", status="INVALID_RESPONSE")
        accounts: list[SaxoAccount] = []
        for row in rows:
            if not isinstance(row, dict) or not row.get("AccountKey"):
                continue
            accounts.append(
                SaxoAccount(
                    account_key=str(row["AccountKey"]),
                    account_id=str(row.get("AccountId") or row["AccountKey"]),
                    currency=str(row.get("Currency") or ""),
                    active=bool(row.get("Active", True)),
                )
            )
        return tuple(accounts)

    def precheck(self, order: SaxoOrderRequest) -> dict[str, Any]:
        return self._post("trade/v2/orders/precheck", order.payload())

    def place_order(self, order: SaxoOrderRequest, *, confirm_sim: bool = False) -> dict[str, Any]:
        if not confirm_sim:
            raise SaxoTradingSafetyError("SIM-ordre krever eksplisitt confirm_sim=True")
        return self._post("trade/v2/orders", order.payload())

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.client.base_url}/{path.lstrip('/')}"
        response = None
        for attempt in range(2):
            self.client._set_authorization(force_refresh=attempt == 1)
            try:
                response = self.client.session.post(url, json=payload, timeout=self.client.timeout)
            except requests.Timeout as exc:
                raise SaxoError(
                    f"tidsavbrudd etter {self.client.timeout:g} sekunder",
                    status="TIMEOUT",
                ) from exc
            except requests.ConnectionError as exc:
                raise SaxoError("kunne ikke opprette forbindelse", status="CONNECTION_FAILED") from exc
            except requests.RequestException as exc:
                raise SaxoError(type(exc).__name__, status="REQUEST_FAILED") from exc

            if response.status_code == 401 and self.client._access_token_getter is not None and attempt == 0:
                continue
            break

        if response is None:
            raise SaxoError("ingen respons fra Saxo", status="REQUEST_FAILED")
        try:
            body = response.json()
        except ValueError as exc:
            raise SaxoError(
                "responsen var ikke gyldig JSON",
                status="INVALID_RESPONSE",
                status_code=response.status_code,
            ) from exc

        if not response.ok:
            message = "forespørselen ble avvist"
            if isinstance(body, dict):
                error_info = body.get("ErrorInfo") if isinstance(body.get("ErrorInfo"), dict) else {}
                message = str(
                    error_info.get("Message")
                    or error_info.get("ErrorCode")
                    or body.get("Message")
                    or body.get("message")
                    or message
                )
            status = "AUTH_FAILED" if response.status_code in {401, 403} else "REQUEST_FAILED"
            raise SaxoError(message, status=status, status_code=response.status_code)
        if not isinstance(body, dict):
            raise SaxoError("forventet JSON-objekt", status="INVALID_RESPONSE", status_code=response.status_code)
        return body


def configured_trading_client() -> SaxoTradingClient | None:
    client = configured_client()
    if client is None:
        return None
    return SaxoTradingClient(client)
