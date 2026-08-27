from __future__ import annotations

from saxo_low_friction_candidates_v2 import LowFrictionCandidateV2, LowFrictionScanResultV2
from saxo_margin_precheck_v2 import (
    FRACTIONAL_PROBE_AMOUNTS_V2,
    fractional_margin_probe_rows_for_ui_v2,
    margin_precheck_rows_for_ui_v2,
    scan_fractional_margin_probe_v2,
    scan_minimum_margin_prechecks_v2,
)


class FakeResponse:
    def __init__(self, payload, *, status_code=200, headers=None):
        self._payload = payload
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self.headers = headers or {}

    def json(self):
        return self._payload


def _ok_payload(side: str, *, initial_margin: float | None = None):
    if side == "Buy":
        margin = 125.0 if initial_margin is None else initial_margin
        return {
            "PreCheckResult": "Ok",
            "EstimatedCashRequired": 12.5,
            "EstimatedCashRequiredCurrency": "NOK",
            "EstimatedTotalCostInAccountCurrency": 0.45,
            "MarginImpactBuySell": {
                "Currency": "NOK",
                "InitialMarginAvailableCurrent": 1000.0,
                "InitialMarginAvailableBuy": 1000.0 - margin,
                "InitialMarginBuy": margin,
                "MaintenanceMarginBuy": margin * 0.8,
            },
        }
    margin = 130.0 if initial_margin is None else initial_margin
    return {
        "PreCheckResult": "Ok",
        "EstimatedCashRequired": 13.0,
        "EstimatedCashRequiredCurrency": "NOK",
        "EstimatedTotalCostInAccountCurrency": 0.50,
        "MarginImpactBuySell": {
            "Currency": "NOK",
            "InitialMarginAvailableCurrent": 1000.0,
            "InitialMarginAvailableSell": 1000.0 - margin,
            "InitialMarginSell": margin,
            "MaintenanceMarginSell": margin * 0.8,
        },
    }


class FakeSession:
    def __init__(self):
        self.posts = []

    def post(self, url, json=None, timeout=None):
        self.posts.append((url, json, timeout))
        return FakeResponse(_ok_payload(json["BuySell"]))


class FractionalSession(FakeSession):
    def post(self, url, json=None, timeout=None):
        self.posts.append((url, json, timeout))
        if float(json["Amount"]) < 0.1:
            return FakeResponse(
                {"ErrorInfo": {"ErrorCode": "InvalidAmount", "Message": "Amount too small"}},
                status_code=400,
            )
        margin = 80.0 if json["BuySell"] == "Buy" else 85.0
        return FakeResponse(_ok_payload(json["BuySell"], initial_margin=margin))


class RateLimitedSession(FakeSession):
    def __init__(self):
        super().__init__()
        self.rate_limited_once = False

    def post(self, url, json=None, timeout=None):
        self.posts.append((url, json, timeout))
        if not self.rate_limited_once:
            self.rate_limited_once = True
            return FakeResponse(
                {"ErrorInfo": {"ErrorCode": "TooManyRequests", "Message": "Rate limit exceeded"}},
                status_code=429,
                headers={"Retry-After": "0"},
            )
        return FakeResponse(_ok_payload(json["BuySell"]))


class FakeClient:
    def __init__(self, *, session=None):
        self.base_url = "https://gateway.saxobank.com/openapi"
        self.timeout = 20.0
        self.session = session or FakeSession()
        self._access_token_getter = None

    def _set_authorization(self, *, force_refresh=False):
        return None

    def _get(self, path, *, params=None):
        assert path == "port/v1/accounts/me"
        return {
            "Data": [
                {
                    "AccountKey": "acc-key",
                    "AccountId": "INET1234",
                    "Currency": "NOK",
                    "Active": True,
                }
            ]
        }


def _candidate(*, asset_type="CfdOnFutures", market="Brent", minimum_trade_size=25.0, uic=707):
    return LowFrictionCandidateV2(
        market=market,
        uic=uic,
        asset_type=asset_type,
        description="UK Crude, continuous" if market == "Brent" else "US Tech 100 NAS",
        symbol="OILUKcont" if market == "Brent" else "USNAS100.I",
        exchange="Saxo",
        currency="USD",
        matched_queries=(market,),
        bid=87.46,
        ask=87.53,
        spread_pct=0.000068,
        minimum_trade_size=minimum_trade_size,
        minimum_order_value=None,
        increment_size=1.0,
        margin_requirement_pct=None,
        long_commission=0.0,
        short_commission=0.0,
        commission_currency="NOK",
        long_total_cost_pct=0.0,
        short_total_cost_pct=0.0,
        zero_commission_both_sides=True,
        cost_error=None,
        details_error=None,
        provisional_margin_candidate=True,
        live_execution_eligible=False,
    )


def test_live_precheck_posts_only_to_non_mutating_precheck_endpoint():
    client = FakeClient()
    low_friction = LowFrictionScanResultV2(
        market="Brent",
        rows=(_candidate(),),
        precise_rows_seen=1,
        candidate_rows_seen=1,
        inspected=1,
        failed=0,
        account_labels=("…1234 NOK",),
    )

    result = scan_minimum_margin_prechecks_v2(client, low_friction=low_friction)

    assert result.inspected == 1
    assert result.failed_sides == 0
    assert len(client.session.posts) == 2
    assert all(url.endswith("/trade/v2/orders/precheck") for url, _, _ in client.session.posts)
    assert {payload["BuySell"] for _, payload, _ in client.session.posts} == {"Buy", "Sell"}
    assert all(payload["Amount"] == 25.0 for _, payload, _ in client.session.posts)
    assert all(payload["FieldGroups"] == ["MarginImpactBuySell", "Costs"] for _, payload, _ in client.session.posts)


def test_precheck_captures_minimum_buy_and_sell_margin_without_granting_execution():
    client = FakeClient()
    low_friction = LowFrictionScanResultV2(
        market="Brent",
        rows=(_candidate(),),
        precise_rows_seen=1,
        candidate_rows_seen=1,
        inspected=1,
        failed=0,
        account_labels=("…1234 NOK",),
    )

    result = scan_minimum_margin_prechecks_v2(client, low_friction=low_friction)
    row = result.rows[0]

    assert row.buy.ok is True
    assert row.sell.ok is True
    assert row.buy.initial_margin == 125.0
    assert row.sell.initial_margin == 130.0
    assert row.buy.maintenance_margin == 100.0
    assert row.sell.maintenance_margin == 104.0
    assert row.buy.estimated_cash_required == 12.5
    assert row.sell.estimated_cash_required == 13.0
    assert row.buy.margin_currency == "NOK"
    assert row.sell.margin_currency == "NOK"

    ui = margin_precheck_rows_for_ui_v2(result.rows)[0]
    assert ui["Init.margin BUY"] == 125.0
    assert ui["Init.margin SELL"] == 130.0
    assert ui["UIC"] == 707


def test_fractional_probe_finds_smallest_tested_amount_valid_for_both_directions():
    client = FakeClient(session=FractionalSession())
    candidate = _candidate(
        asset_type="CfdOnIndex",
        market="Index CFDs · training",
        minimum_trade_size=None,
        uic=999,
    )

    result = scan_fractional_margin_probe_v2(
        client,
        candidates=(candidate,),
        amount_ladder=FRACTIONAL_PROBE_AMOUNTS_V2,
        pause_seconds=0,
    )

    assert result.inspected == 1
    assert result.precheck_calls == 4
    row = result.rows[0]
    assert row.tested_amounts == (0.01, 0.1)
    assert row.amount == 0.1
    assert row.both_sides_ok is True
    assert row.max_initial_margin == 85.0
    assert all(url.endswith("/trade/v2/orders/precheck") for url, _, _ in client.session.posts)
    assert [payload["Amount"] for _, payload, _ in client.session.posts] == [0.01, 0.01, 0.1, 0.1]

    ui = fractional_margin_probe_rows_for_ui_v2(result.rows)[0]
    assert ui["Begge retninger OK"] is True
    assert ui["Min. testet amount"] == 0.1
    assert ui["Max init.margin"] == 85.0


def test_precheck_retries_429_without_changing_endpoint():
    client = FakeClient(session=RateLimitedSession())
    candidate = _candidate(
        asset_type="CfdOnIndex",
        market="Index CFDs · training",
        minimum_trade_size=None,
        uic=1001,
    )

    result = scan_fractional_margin_probe_v2(
        client,
        candidates=(candidate,),
        amount_ladder=(0.01,),
        pause_seconds=0,
    )

    assert result.rows[0].both_sides_ok is True
    assert len(client.session.posts) == 3
    assert all(url.endswith("/trade/v2/orders/precheck") for url, _, _ in client.session.posts)
    assert all(payload["Uic"] == 1001 for _, payload, _ in client.session.posts)
