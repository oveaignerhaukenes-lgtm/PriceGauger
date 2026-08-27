from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any, Iterable

import requests

from saxo_low_friction_candidates_v2 import LowFrictionCandidateV2, LowFrictionScanResultV2
from saxo_provider import SaxoClient, SaxoError, SaxoInstrument


PRECHECK_PATH_V2 = "trade/v2/orders/precheck"
FRACTIONAL_PROBE_AMOUNTS_V2: tuple[float, ...] = (0.01, 0.1, 1.0)


@dataclass(frozen=True, slots=True)
class MarginPrecheckSideV2:
    side: str
    precheck_result: str | None
    estimated_cash_required: float | None
    estimated_cash_currency: str | None
    estimated_total_cost_account: float | None
    initial_margin: float | None
    maintenance_margin: float | None
    margin_currency: str | None
    initial_margin_available_current: float | None
    initial_margin_available_after: float | None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return (self.precheck_result or "").lower() == "ok" and self.error is None


@dataclass(frozen=True, slots=True)
class MarginPrecheckCandidateV2:
    uic: int
    asset_type: str
    description: str
    symbol: str
    amount: float
    buy: MarginPrecheckSideV2
    sell: MarginPrecheckSideV2


@dataclass(frozen=True, slots=True)
class MarginPrecheckScanResultV2:
    rows: tuple[MarginPrecheckCandidateV2, ...]
    inspected: int
    failed_sides: int
    account_label: str | None


@dataclass(frozen=True, slots=True)
class FractionalMarginProbeCandidateV2:
    uic: int
    asset_type: str
    description: str
    symbol: str
    spread_pct: float | None
    zero_commission_both_sides: bool | None
    tested_amounts: tuple[float, ...]
    amount: float | None
    buy: MarginPrecheckSideV2
    sell: MarginPrecheckSideV2

    @property
    def both_sides_ok(self) -> bool:
        return self.amount is not None and self.buy.ok and self.sell.ok

    @property
    def max_initial_margin(self) -> float | None:
        values = [value for value in (self.buy.initial_margin, self.sell.initial_margin) if value is not None]
        return max(values) if values else None

    @property
    def max_maintenance_margin(self) -> float | None:
        values = [value for value in (self.buy.maintenance_margin, self.sell.maintenance_margin) if value is not None]
        return max(values) if values else None

    @property
    def max_cash_required(self) -> float | None:
        values = [
            value
            for value in (self.buy.estimated_cash_required, self.sell.estimated_cash_required)
            if value is not None
        ]
        return max(values) if values else None

    @property
    def max_total_cost_account(self) -> float | None:
        values = [
            value
            for value in (self.buy.estimated_total_cost_account, self.sell.estimated_total_cost_account)
            if value is not None
        ]
        return max(values) if values else None


@dataclass(frozen=True, slots=True)
class FractionalMarginProbeResultV2:
    rows: tuple[FractionalMarginProbeCandidateV2, ...]
    inspected: int
    precheck_calls: int
    account_label: str | None
    amount_ladder: tuple[float, ...]


def _number(value: Any, *, allow_zero: bool = True) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if allow_zero:
        return number if number >= 0 else None
    return number if number > 0 else None


def _error_message(payload: dict[str, Any]) -> str | None:
    info = payload.get("ErrorInfo") if isinstance(payload.get("ErrorInfo"), dict) else {}
    message = (
        info.get("Message")
        or info.get("ErrorCode")
        or payload.get("Message")
        or payload.get("message")
    )
    return str(message) if message else None


def _retry_after_seconds(response: Any) -> float:
    headers = getattr(response, "headers", None)
    if headers:
        value = headers.get("Retry-After") or headers.get("retry-after")
        try:
            delay = float(value)
        except (TypeError, ValueError):
            delay = None
        if delay is not None and delay >= 0:
            return min(delay, 5.0)
    return 0.75


def _post_precheck_only_v2(client: SaxoClient, payload: dict[str, Any]) -> dict[str, Any]:
    """POST only to Saxo's non-mutating precheck endpoint.

    This deliberately does not accept an arbitrary path. The scanner can inspect
    LIVE margin/cash requirements but cannot place, amend or cancel an order.
    Saxo documents this endpoint as Personal: Read.

    429 responses are retried conservatively because property browsing may issue a
    short sequence of prechecks. No mutating order endpoint is ever retried here.
    """

    url = f"{client.base_url}/{PRECHECK_PATH_V2}"
    response = None
    force_refresh = False
    for attempt in range(3):
        client._set_authorization(force_refresh=force_refresh)
        force_refresh = False
        try:
            response = client.session.post(url, json=payload, timeout=client.timeout)
        except requests.Timeout as exc:
            raise SaxoError(f"tidsavbrudd etter {client.timeout:g} sekunder", status="TIMEOUT") from exc
        except requests.ConnectionError as exc:
            raise SaxoError("kunne ikke opprette forbindelse", status="CONNECTION_FAILED") from exc
        except requests.RequestException as exc:
            raise SaxoError(type(exc).__name__, status="REQUEST_FAILED") from exc

        if response.status_code == 401 and client._access_token_getter is not None and attempt < 2:
            force_refresh = True
            continue
        if response.status_code == 429 and attempt < 2:
            time.sleep(_retry_after_seconds(response))
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
    if not isinstance(body, dict):
        raise SaxoError("forventet JSON-objekt", status="INVALID_RESPONSE", status_code=response.status_code)
    if not response.ok:
        raise SaxoError(
            _error_message(body) or "precheck ble avvist",
            status="AUTH_FAILED" if response.status_code in {401, 403} else "REQUEST_FAILED",
            status_code=response.status_code,
        )
    return body


def _margin_value(margin: dict[str, Any], base: str, side: str) -> float | None:
    suffix = "Buy" if side == "Buy" else "Sell"
    for key in (f"{base}{suffix}", base):
        value = _number(margin.get(key))
        if value is not None:
            return value
    return None


def _side_precheck_v2(
    client: SaxoClient,
    *,
    account_key: str,
    instrument: SaxoInstrument,
    amount: float,
    side: str,
) -> MarginPrecheckSideV2:
    normalized_side = str(side).title()
    if normalized_side not in {"Buy", "Sell"}:
        raise ValueError("side must be Buy or Sell")
    payload = {
        "AccountKey": account_key,
        "Amount": float(amount),
        "AssetType": instrument.asset_type,
        "BuySell": normalized_side,
        "FieldGroups": ["MarginImpactBuySell", "Costs"],
        "IsForceOpen": False,
        "ManualOrder": True,
        "OrderDuration": {"DurationType": "DayOrder"},
        "OrderType": "Market",
        "Uic": int(instrument.uic),
    }
    try:
        body = _post_precheck_only_v2(client, payload)
    except Exception as exc:
        return MarginPrecheckSideV2(
            side=normalized_side,
            precheck_result=None,
            estimated_cash_required=None,
            estimated_cash_currency=None,
            estimated_total_cost_account=None,
            initial_margin=None,
            maintenance_margin=None,
            margin_currency=None,
            initial_margin_available_current=None,
            initial_margin_available_after=None,
            error=f"{type(exc).__name__}: {exc}",
        )

    margin = body.get("MarginImpactBuySell") if isinstance(body.get("MarginImpactBuySell"), dict) else {}
    result = str(body.get("PreCheckResult") or "") or None
    response_error = _error_message(body)
    if result and result.lower() != "ok" and response_error is None:
        response_error = f"PreCheckResult={result}"

    return MarginPrecheckSideV2(
        side=normalized_side,
        precheck_result=result,
        estimated_cash_required=_number(body.get("EstimatedCashRequired")),
        estimated_cash_currency=str(body.get("EstimatedCashRequiredCurrency") or "") or None,
        estimated_total_cost_account=_number(body.get("EstimatedTotalCostInAccountCurrency")),
        initial_margin=_margin_value(margin, "InitialMargin", normalized_side),
        maintenance_margin=_margin_value(margin, "MaintenanceMargin", normalized_side),
        margin_currency=str(margin.get("Currency") or "") or None,
        initial_margin_available_current=_number(margin.get("InitialMarginAvailableCurrent")),
        initial_margin_available_after=_margin_value(margin, "InitialMarginAvailable", normalized_side),
        error=response_error,
    )


def _active_account_v2(client: SaxoClient) -> tuple[str, str] | None:
    account_payload = client._get("port/v1/accounts/me")
    accounts = account_payload.get("Data") or []
    account = next(
        (
            item
            for item in accounts
            if isinstance(item, dict) and item.get("AccountKey") and item.get("Active") is not False
        ),
        None,
    ) if isinstance(accounts, list) else None
    if account is None:
        return None
    account_key = str(account["AccountKey"])
    account_id = str(account.get("AccountId") or "")
    account_currency = str(account.get("Currency") or "")
    suffix = account_id[-4:] if account_id else "????"
    return account_key, f"…{suffix} {account_currency}".strip()


def scan_minimum_margin_prechecks_v2(
    client: SaxoClient,
    *,
    low_friction: LowFrictionScanResultV2,
) -> MarginPrecheckScanResultV2:
    """Precheck minimum BUY and SELL for each low-friction candidate.

    The result is observational and account-state dependent. It never grants
    execution eligibility and the implementation has no order-placement endpoint.
    """

    account = _active_account_v2(client)
    if account is None:
        return MarginPrecheckScanResultV2(rows=(), inspected=0, failed_sides=0, account_label=None)
    account_key, label = account

    rows: list[MarginPrecheckCandidateV2] = []
    failed_sides = 0
    for candidate in low_friction.rows:
        amount = float(candidate.minimum_trade_size or candidate.increment_size or 1.0)
        if amount <= 0:
            continue
        instrument = SaxoInstrument(
            asset=candidate.market,
            uic=int(candidate.uic),
            asset_type=str(candidate.asset_type),
            symbol=str(candidate.symbol or ""),
            description=str(candidate.description or ""),
        )
        buy = _side_precheck_v2(
            client,
            account_key=account_key,
            instrument=instrument,
            amount=amount,
            side="Buy",
        )
        sell = _side_precheck_v2(
            client,
            account_key=account_key,
            instrument=instrument,
            amount=amount,
            side="Sell",
        )
        failed_sides += int(not buy.ok) + int(not sell.ok)
        rows.append(
            MarginPrecheckCandidateV2(
                uic=instrument.uic,
                asset_type=instrument.asset_type,
                description=instrument.description or instrument.symbol or f"UIC {instrument.uic}",
                symbol=instrument.symbol,
                amount=amount,
                buy=buy,
                sell=sell,
            )
        )

    def _rank(item: MarginPrecheckCandidateV2) -> tuple[float, float, str, int]:
        margins = [value for value in (item.buy.initial_margin, item.sell.initial_margin) if value is not None]
        cash = [value for value in (item.buy.estimated_cash_required, item.sell.estimated_cash_required) if value is not None]
        margin_rank = max(margins) if margins else float("inf")
        cash_rank = max(cash) if cash else float("inf")
        return margin_rank, cash_rank, item.description.lower(), item.uic

    rows.sort(key=_rank)
    return MarginPrecheckScanResultV2(
        rows=tuple(rows),
        inspected=len(rows),
        failed_sides=failed_sides,
        account_label=label,
    )


def scan_fractional_margin_probe_v2(
    client: SaxoClient,
    *,
    candidates: Iterable[LowFrictionCandidateV2],
    max_candidates: int = 5,
    amount_ladder: Iterable[float] = FRACTIONAL_PROBE_AMOUNTS_V2,
    pause_seconds: float = 0.35,
) -> FractionalMarginProbeResultV2:
    """Find the smallest tested amount that Saxo accepts for both BUY and SELL.

    This is a read-only browser probe, not an execution path. It intentionally
    tests only a small, explicit amount ladder and a bounded shortlist to avoid
    hammering Saxo's precheck service. The result is "smallest tested amount that
    works now", not a contractual MinimumTradeSize declaration.
    """

    account = _active_account_v2(client)
    amounts = tuple(sorted({float(value) for value in amount_ladder if float(value) > 0}))
    if account is None or not amounts:
        return FractionalMarginProbeResultV2(
            rows=(),
            inspected=0,
            precheck_calls=0,
            account_label=None if account is None else account[1],
            amount_ladder=amounts,
        )
    account_key, label = account

    shortlist = tuple(candidates)[: max(1, int(max_candidates))]
    rows: list[FractionalMarginProbeCandidateV2] = []
    precheck_calls = 0
    pause = max(float(pause_seconds), 0.0)

    for candidate_index, candidate in enumerate(shortlist):
        instrument = SaxoInstrument(
            asset=candidate.market,
            uic=int(candidate.uic),
            asset_type=str(candidate.asset_type),
            symbol=str(candidate.symbol or ""),
            description=str(candidate.description or ""),
        )
        tested: list[float] = []
        chosen_amount: float | None = None
        last_buy = MarginPrecheckSideV2("Buy", None, None, None, None, None, None, None, None, None, "not tested")
        last_sell = MarginPrecheckSideV2("Sell", None, None, None, None, None, None, None, None, None, "not tested")

        for amount_index, amount in enumerate(amounts):
            tested.append(amount)
            last_buy = _side_precheck_v2(
                client,
                account_key=account_key,
                instrument=instrument,
                amount=amount,
                side="Buy",
            )
            precheck_calls += 1
            if pause and (candidate_index or amount_index or True):
                time.sleep(pause)
            last_sell = _side_precheck_v2(
                client,
                account_key=account_key,
                instrument=instrument,
                amount=amount,
                side="Sell",
            )
            precheck_calls += 1
            if last_buy.ok and last_sell.ok:
                chosen_amount = amount
                break
            if pause:
                time.sleep(pause)

        rows.append(
            FractionalMarginProbeCandidateV2(
                uic=candidate.uic,
                asset_type=candidate.asset_type,
                description=candidate.description,
                symbol=candidate.symbol,
                spread_pct=candidate.spread_pct,
                zero_commission_both_sides=candidate.zero_commission_both_sides,
                tested_amounts=tuple(tested),
                amount=chosen_amount,
                buy=last_buy,
                sell=last_sell,
            )
        )

    def _rank(item: FractionalMarginProbeCandidateV2) -> tuple[int, int, float, float, float, str, int]:
        return (
            0 if item.both_sides_ok else 1,
            0 if item.zero_commission_both_sides is True else 1,
            float("inf") if item.max_initial_margin is None else item.max_initial_margin,
            float("inf") if item.spread_pct is None else item.spread_pct,
            float("inf") if item.amount is None else item.amount,
            item.description.lower(),
            item.uic,
        )

    rows.sort(key=_rank)
    return FractionalMarginProbeResultV2(
        rows=tuple(rows),
        inspected=len(rows),
        precheck_calls=precheck_calls,
        account_label=label,
        amount_ladder=amounts,
    )


def margin_precheck_rows_for_ui_v2(rows: Iterable[MarginPrecheckCandidateV2]) -> list[dict[str, object]]:
    return [
        {
            "Produkt": item.description,
            "Symbol": item.symbol,
            "AssetType": item.asset_type,
            "Min. amount": item.amount,
            "BUY": item.buy.precheck_result or "",
            "Cash BUY": item.buy.estimated_cash_required,
            "Cash-valuta": item.buy.estimated_cash_currency or item.sell.estimated_cash_currency or "",
            "Init.margin BUY": item.buy.initial_margin,
            "Maint.margin BUY": item.buy.maintenance_margin,
            "SELL": item.sell.precheck_result or "",
            "Cash SELL": item.sell.estimated_cash_required,
            "Init.margin SELL": item.sell.initial_margin,
            "Maint.margin SELL": item.sell.maintenance_margin,
            "Marginvaluta": item.buy.margin_currency or item.sell.margin_currency or "",
            "Total kost BUY (konto)": item.buy.estimated_total_cost_account,
            "Total kost SELL (konto)": item.sell.estimated_total_cost_account,
            "BUY-feil": item.buy.error or "",
            "SELL-feil": item.sell.error or "",
            "UIC": item.uic,
        }
        for item in rows
    ]


def fractional_margin_probe_rows_for_ui_v2(
    rows: Iterable[FractionalMarginProbeCandidateV2],
) -> list[dict[str, object]]:
    return [
        {
            "Produkt": item.description,
            "Symbol": item.symbol,
            "AssetType": item.asset_type,
            "Begge retninger OK": item.both_sides_ok,
            "Min. testet amount": item.amount,
            "Max init.margin": item.max_initial_margin,
            "Max maint.margin": item.max_maintenance_margin,
            "Max cash": item.max_cash_required,
            "Marginvaluta": item.buy.margin_currency or item.sell.margin_currency or "",
            "0 kurtasje": item.zero_commission_both_sides,
            "Spread %": None if item.spread_pct is None else item.spread_pct * 100.0,
            "Max total kost (konto)": item.max_total_cost_account,
            "BUY": item.buy.precheck_result or "",
            "SELL": item.sell.precheck_result or "",
            "Testet": " → ".join(f"{value:g}" for value in item.tested_amounts),
            "BUY-feil": item.buy.error or "",
            "SELL-feil": item.sell.error or "",
            "UIC": item.uic,
        }
        for item in rows
    ]
