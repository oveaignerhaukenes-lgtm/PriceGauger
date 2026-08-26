from __future__ import annotations

from saxo_low_friction_candidates_v2 import LowFrictionCandidateV2, LowFrictionScanResultV2
from saxo_margin_precheck_v2 import margin_precheck_rows_for_ui_v2, scan_minimum_margin_prechecks_v2


class FakeResponse:
    def __init__(self, payload, *, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.ok = 200 <= status_code < 300

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self):
        self.posts = []

    def post(self, url, json=None, timeout=None):
        self.posts.append((url, json, timeout))
        side = json["BuySell"]
        if side == "Buy":
            return FakeResponse(
                {
                    "PreCheckResult": "Ok",
                    "EstimatedCashRequired": 12.5,
                    "EstimatedCashRequiredCurrency": "NOK",
                    "EstimatedTotalCostInAccountCurrency": 0.45,
                    "MarginImpactBuySell": {
                        "Currency": "NOK",
                        "InitialMarginAvailableCurrent": 1000.0,
                        "InitialMarginAvailableBuy": 875.0,
                        "InitialMarginBuy": 125.0,
                        "MaintenanceMarginBuy": 100.0,
                    },
                }
            )
        return FakeResponse(
            {
                "PreCheckResult": "Ok",
                "EstimatedCashRequired": 13.0,
                "EstimatedCashRequiredCurrency": "NOK",
                "EstimatedTotalCostInAccountCurrency": 0.50,
                "MarginImpactBuySell": {
                    "Currency": "NOK",
                    "InitialMarginAvailableCurrent": 1000.0,
                    "InitialMarginAvailableSell": 870.0,
                    "InitialMarginSell": 130.0,
                    "MaintenanceMarginSell": 104.0,
                },
            }
        )


class FakeClient:
    def __init__(self):
        self.base_url = "https://gateway.saxobank.com/openapi"
        self.timeout = 20.0
        self.session = FakeSession()
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


def _candidate():
    return LowFrictionCandidateV2(
        market="Brent",
        uic=707,
        asset_type="CfdOnFutures",
        description="UK Crude, continuous",
        symbol="OILUKcont",
        exchange="Saxo",
        currency="USD",
        matched_queries=("Brent",),
        bid=87.46,
        ask=87.53,
        spread_pct=0.0008,
        minimum_trade_size=25.0,
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
