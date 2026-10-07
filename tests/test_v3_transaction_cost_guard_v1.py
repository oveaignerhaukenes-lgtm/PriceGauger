from pathlib import Path

from autotrader_v3_cost_guard_v1 import assess_transaction_cost_v3


class _Client:
    def __init__(self, total_pct, commission=0.0):
        self.total_pct = total_pct
        self.commission = commission
        self.calls = []

    def _get(self, path, params=None):
        self.calls.append((path, dict(params or {})))
        if path.startswith("ref/v1/instruments/details/"):
            return {
                "AssetType": "CfdOnStock",
                "IsTradable": True,
                "NonTradableReason": "None",
                "AmountDecimals": 0,
                "MinimumTradeSize": 1,
                "ContractSize": 1,
                "SupportedOrderTypes": ["Market"],
                "CurrencyCode": "GBP",
            }
        if path == "trade/v1/infoprices":
            return {"Quote": {"Bid": 54.9, "Ask": 55.0, "Mid": 54.95}}
        if path.startswith("cs/v1/tradingconditions/cost/"):
            if self.total_pct is None:
                return {"Cost": {"Long": {}, "Short": {}}}
            side = {
                "Currency": "NOK",
                "TotalCostPct": self.total_pct,
                "TradingCost": {
                    "Commissions": [{"Value": self.commission}]
                },
            }
            return {
                "AccountCurrency": "NOK",
                "Cost": {"Long": side, "Short": side},
                "CostCalculationAssumptions": [
                    "IncludesOpenAndCloseCost",
                    "EquivalentOpenAndClosePrice",
                ],
            }
        raise AssertionError(path)


class _Broker:
    def __init__(self, client):
        self.client = client

    def accounts(self):
        return (
            {
                "AccountId": "SILVER",
                "AccountKey": "key-1",
                "Currency": "NOK",
            },
        )


def _assess(total_pct, commission=0.0, amount=None):
    client = _Client(total_pct, commission=commission)
    result = assess_transaction_cost_v3(
        broker=_Broker(client),
        account_id="SILVER",
        market_name="WisdomTree Physical Silver ETC",
        uic=36078,
        asset_type="CfdOnStock",
        amount=amount,
    )
    return result, client


def test_low_transaction_cost_is_green():
    result, _ = _assess(0.10, commission=0.0)
    assert result.severity == "GREEN"
    assert result.blocked is False
    assert result.max_total_cost_pct == 0.10


def test_moderately_expensive_transaction_cost_is_yellow():
    result, _ = _assess(0.75, commission=10.0)
    assert result.severity == "YELLOW"
    assert result.blocked is False
    assert result.long_commission == 10.0


def test_high_round_trip_cost_blocks_live():
    result, _ = _assess(25.0, commission=100.0)
    assert result.severity == "RED"
    assert result.blocked is True
    assert "LIVE sperret" in result.detail
    assert result.long_commission == 100.0
    assert "IncludesOpenAndCloseCost" in result.assumptions


def test_unverifiable_cost_fails_closed():
    result, _ = _assess(None)
    assert result.severity == "RED"
    assert result.blocked is True
    assert "kunne ikke verifiseres" in result.detail


def test_explicit_runtime_amount_skips_second_instrument_details_lookup():
    result, client = _assess(0.1, amount=1.0)
    assert result.severity == "GREEN"
    assert not any(path.startswith("ref/v1/instruments/details/") for path, _ in client.calls)


def test_ui_and_runtime_enforce_cost_guard_without_trapping_reductions():
    ui = Path("autotrader_v3_instance_controls_ui_v1.py").read_text(encoding="utf-8")
    runtime = Path("autotrader_v3_live_runtime_v1.py").read_text(encoding="utf-8")

    assert "cost_blocked" in ui
    assert "disabled=bool(live_issues or cost_blocked)" in ui
    assert "LIVE kostnadssperre" in ui

    assert "assess_transaction_cost_v3(" in runtime
    assert "cost_assessment.blocked and abs(actual.amount) <= 1e-12" in runtime
    open_add = runtime.index("if mutation.action in {'OPEN','ADD'}:")
    cost_block = runtime.index("if cost_assessment.blocked:", open_add)
    reduce_close = runtime.index("if mutation.action in {'REDUCE','CLOSE'}:")
    assert reduce_close < open_add < cost_block
