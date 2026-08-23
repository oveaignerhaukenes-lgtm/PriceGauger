from __future__ import annotations

import autotrader_risk_dry_run_v2 as risk


def _position(
    *,
    pnl_pct: float,
    direction: str = "Buy",
    delay: int = 0,
    can_close: bool = True,
    reliability: str = "Ok",
    market_open: bool = True,
    non_tradable_reason: str = "None",
) -> risk.PositionObservationV2:
    return risk.PositionObservationV2(
        account_id="acct",
        net_position_id="position-1",
        uic=123,
        asset_type="CfdOnIndex",
        direction=direction,
        amount=1.0,
        average_open_price=100.0,
        current_price=100.0,
        pnl_pct=pnl_pct,
        price_delay_minutes=delay,
        can_be_closed=can_close,
        calculation_reliability=reliability,
        is_market_open=market_open,
        non_tradable_reason=non_tradable_reason,
    )


def test_default_contract_matches_requested_risk_limits() -> None:
    config = risk.RiskConfigV2()
    assert config.hard_stop_pct == -1.0
    assert config.trailing_activation_pct == 2.0
    assert config.trailing_drawdown_pct == 0.5
    assert config.fixed_take_profit_enabled is False
    assert config.max_price_delay_minutes == 0


def test_position_return_is_product_price_return_not_account_or_margin_return() -> None:
    assert risk.pnl_percent_v2(average_open_price=100.0, current_price=101.0, direction="Buy") == 1.0
    assert risk.pnl_percent_v2(average_open_price=100.0, current_price=99.0, direction="Sell") == 1.0
    assert risk.pnl_percent_v2(average_open_price=100.0, current_price=101.0, direction="Sell") == -1.0


def test_hard_stop_emits_would_close() -> None:
    decision = risk.evaluate_risk_v2(_position(pnl_pct=-1.01), config=risk.RiskConfigV2())
    assert decision.action == risk.ACTION_WOULD_CLOSE
    assert decision.reason == risk.REASON_HARD_STOP
    assert decision.eligible_for_execution is True


def test_trailing_activates_only_after_profit_threshold() -> None:
    before = risk.evaluate_risk_v2(
        _position(pnl_pct=1.4),
        config=risk.RiskConfigV2(),
        previous_high_water_pct=1.9,
    )
    assert before.action == risk.ACTION_HOLD
    assert before.trailing_floor_pct is None

    after = risk.evaluate_risk_v2(
        _position(pnl_pct=2.2),
        config=risk.RiskConfigV2(),
        previous_high_water_pct=2.8,
    )
    assert after.action == risk.ACTION_WOULD_CLOSE
    assert after.reason == risk.REASON_TRAILING_STOP
    assert round(after.trailing_floor_pct or 0.0, 6) == 2.3


def test_trailing_high_water_never_moves_down() -> None:
    decision = risk.evaluate_risk_v2(
        _position(pnl_pct=2.6),
        config=risk.RiskConfigV2(),
        previous_high_water_pct=3.0,
    )
    assert decision.high_water_pct == 3.0
    assert decision.trailing_floor_pct == 2.5
    assert decision.action == risk.ACTION_HOLD


def test_optional_fixed_take_profit() -> None:
    config = risk.RiskConfigV2(fixed_take_profit_enabled=True, fixed_take_profit_pct=4.0)
    decision = risk.evaluate_risk_v2(_position(pnl_pct=4.1), config=config)
    assert decision.action == risk.ACTION_WOULD_CLOSE
    assert decision.reason == risk.REASON_FIXED_TAKE_PROFIT


def test_delayed_price_blocks_close_signal_even_beyond_hard_stop() -> None:
    config = risk.RiskConfigV2(max_price_delay_minutes=0)
    decision = risk.evaluate_risk_v2(_position(pnl_pct=-3.0, delay=1), config=config)
    assert decision.action == risk.ACTION_HOLD
    assert decision.reason == risk.REASON_PRICE_DELAYED
    assert decision.eligible_for_execution is False


def test_closed_or_nontradable_market_blocks_actionability() -> None:
    closed = risk.evaluate_risk_v2(
        _position(pnl_pct=-5.0, market_open=False),
        config=risk.RiskConfigV2(),
    )
    restricted = risk.evaluate_risk_v2(
        _position(pnl_pct=-5.0, non_tradable_reason="TemporarilyUnavailable"),
        config=risk.RiskConfigV2(),
    )
    assert closed.action == risk.ACTION_HOLD
    assert closed.reason == risk.REASON_MARKET_CLOSED
    assert closed.eligible_for_execution is False
    assert restricted.action == risk.ACTION_HOLD
    assert restricted.reason == risk.REASON_NON_TRADABLE
    assert restricted.eligible_for_execution is False


def test_uncloseable_or_unreliable_position_is_never_actionable() -> None:
    uncloseable = risk.evaluate_risk_v2(_position(pnl_pct=-5.0, can_close=False), config=risk.RiskConfigV2())
    unreliable = risk.evaluate_risk_v2(
        _position(pnl_pct=-5.0, reliability="NoMarketData"),
        config=risk.RiskConfigV2(),
    )
    assert uncloseable.action == risk.ACTION_HOLD
    assert uncloseable.reason == risk.REASON_NOT_CLOSEABLE
    assert unreliable.action == risk.ACTION_HOLD
    assert unreliable.reason == risk.REASON_UNRELIABLE


def test_net_position_adapter_uses_saxo_price_and_tradability_fields() -> None:
    class Client:
        def _get(self, path, params=None):
            assert path == "port/v1/netpositions/me"
            return {
                "Data": [
                    {
                        "NetPositionId": "ABC_CfdOnIndex",
                        "NetPositionBase": {
                            "AccountId": "A1",
                            "Amount": -2,
                            "AssetType": "CfdOnIndex",
                            "CanBeClosed": True,
                            "IsMarketOpen": True,
                            "NonTradableReason": "None",
                            "OpeningDirection": "Sell",
                            "SinglePositionStatus": "Open",
                            "Uic": 42,
                        },
                        "NetPositionView": {
                            "AverageOpenPriceIncludingCosts": 100.0,
                            "CalculationReliability": "Ok",
                            "CurrentPrice": 99.0,
                            "CurrentPriceDelayMinutes": 0,
                            "Status": "Open",
                        },
                    }
                ]
            }

    observations = risk._position_observations_v2(Client())
    assert len(observations) == 1
    assert observations[0].direction == "Sell"
    assert observations[0].amount == 2.0
    assert observations[0].pnl_pct == 1.0
    assert observations[0].is_market_open is True
    assert observations[0].non_tradable_reason == "None"


def test_inactive_state_is_not_reused_as_same_position_lifecycle() -> None:
    source = open("autotrader_risk_dry_run_v2.py", encoding="utf-8").read()
    assert 'bool(previous.get("active"))' in source
    assert "triggered_at, active" in source


def test_risk_module_is_read_only_dry_run() -> None:
    source = open("autotrader_risk_dry_run_v2.py", encoding="utf-8").read()
    assert "place_order(" not in source
    assert ".precheck(" not in source
    assert "trade/v2/orders" not in source
    assert risk.ACTION_WOULD_CLOSE == "WOULD_CLOSE"
