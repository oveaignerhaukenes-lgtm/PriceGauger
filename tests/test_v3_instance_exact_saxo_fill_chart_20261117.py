"""Read-only, account-specific V3 inspection fills; no retrospective high/low."""
from datetime import datetime, timedelta, timezone
import pytest

from autotrader_v3_instance_fill_prices_v1 import (
    attach_verified_fill_prices_v1, fetch_exact_final_fills_v1,
    match_exact_final_fills_v1,
)
from autotrader_v3_instance_inspection_v1 import build_instance_inspection_payload_v1
from trading_desk import ChartBar


START = datetime(2026, 11, 17, 9, 0, tzinfo=timezone.utc)


def _event(order="order-1", side="Sell", amount=.02):
    return {
        "broker_order_id": order,
        "executed_at": START+timedelta(minutes=7, seconds=25),
        "instance_id": "T100C", "account_id": "account-c",
        "action": "OPEN", "side": side, "amount": amount,
        "inventory_after": -.02 if side.lower()=="sell" else .02,
    }


def _activity(order="order-1", **changes):
    return {
        "OrderId": order, "Status": "FinalFill", "SubStatus": "Confirmed",
        "AccountId": "account-c", "Uic": 4912, "AssetType": "CfdOnIndex",
        "BuySell": "Sell", "FilledAmount": .02, "AveragePrice": 27031.35,
        "ActivityTime": (START+timedelta(minutes=7, seconds=11)).isoformat(),
        "LogId": "log-1", **changes,
    }


def _bars():
    return tuple(ChartBar(
        market="US Tech100",
        bar_time=(START+timedelta(minutes=i)).isoformat(),
        open=100+i, high=108+i, low=95+i, close=102+i, volume=1.,
    ) for i in range(10))


def _marker(events, **options):
    payload=build_instance_inspection_payload_v1(
        _bars(), executions=events, timeframe_minutes=1,
        instance_id="T100C", account_id="account-c", **options,
    )
    return [x for x in payload["markers"] if x["source"]=="AUTOTRADER_V3"]


def test_exact_broker_fill_only_when_order_account_product_side_amount_agree():
    fills=match_exact_final_fills_v1(
        [_event()], [_activity(),
                   _activity(order="unrelated", LogId="other"),
                   _activity(AccountId="account-d", LogId="different")],
        account_id="account-c", uic=4912, asset_type="CfdOnIndex",
    )
    assert list(fills)==["order-1"]
    assert fills["order-1"]["execution_price"]==27031.35
    assert fills["order-1"]["price_source"]=="SAXO_FINAL_FILL"
    for change in ({"AccountId":"account-d"}, {"Uic":999},
                   {"AssetType":"CfdOnStock"}, {"BuySell":"Buy"},
                   {"FilledAmount":.01}, {"Status":"Cancelled"},
                   {"AveragePrice":None,"Price":None}):
        assert not match_exact_final_fills_v1(
            [_event()], [_activity(**change)], account_id="account-c",
            uic=4912, asset_type="CfdOnIndex",
        )


def test_partial_saxo_fills_weighted_and_incomplete_set_rejected():
    rows=[_activity(LogId="part1", FilledAmount=.01, Price=100.),
          _activity(LogId="part2", FilledAmount=.01, Price=110.)]
    matched=match_exact_final_fills_v1(
        [_event()], rows, account_id="account-c", uic=4912,
        asset_type="CfdOnIndex",
    )
    assert matched["order-1"]["execution_price"]==105.
    assert not match_exact_final_fills_v1(
        [_event()], [_activity(LogId="part1", FilledAmount=.01),
                     _activity(LogId="part2", FilledAmount=.01)],
        account_id="account-c", uic=4912, asset_type="CfdOnIndex",
    )
    assert not match_exact_final_fills_v1(
        [_event()], rows[:1], account_id="account-c", uic=4912,
        asset_type="CfdOnIndex",
    )


def test_inspection_marker_uses_exact_fill_not_candle_extreme_or_reconciliation_time():
    fill=match_exact_final_fills_v1(
        [_event()], [_activity()], account_id="account-c", uic=4912,
        asset_type="CfdOnIndex",
    )
    marker=_marker(attach_verified_fill_prices_v1([_event()], fill))[0]
    assert marker["price"]==27031.35
    assert marker["price_verified"] is True
    assert marker["price_source"]=="SAXO_FINAL_FILL"
    assert marker["time"]==int((START+timedelta(minutes=7)).timestamp())
    assert marker["price"]!=_bars()[7].high


def test_inspection_estimate_uses_previous_completed_close_not_best_case_high_low():
    marker=_marker([_event()])[0]
    assert marker["price"]==_bars()[6].close
    assert marker["price_verified"] is False
    assert marker["price_source"]=="PREVIOUS_CLOSED_BAR_REFERENCE"
    assert marker["price"]!=_bars()[7].high
    assert marker["price"]!=_bars()[7].low


def test_no_estimated_fill_is_plotted_when_previous_complete_bar_is_missing():
    bars=tuple(bar for i,bar in enumerate(_bars()) if i!=6)
    payload=build_instance_inspection_payload_v1(
        bars,executions=[_event()],timeframe_minutes=1,
        account_id="account-c",instance_id="T100C",
    )
    assert not [x for x in payload["markers"] if x["source"]=="AUTOTRADER_V3"]


def test_chart_filters_account_and_instance_even_if_wrong_ledger_rows_provided():
    assert not _marker([_event() | {"account_id":"account-d"},
                        _event() | {"instance_id":"other"}])
    assert len(_marker([_event(), _event() | {"account_id":"account-d"}]))==1


def test_saxo_audit_is_bounded_read_only_and_fails_closed_if_paginated():
    calls=[]

    class Audit:
        def __init__(self, page):
            self.page=page

        def _get(self, path, *, params):
            calls.append((path, params))
            return self.page

    class Broker:
        def __init__(self, page):
            self.client=Audit(page)

        def _account_context_exact(self, requested):
            assert requested=="account-c"
            return "account-key-c", "client-key-c"

    matched=fetch_exact_final_fills_v1(
        [_event()], account_id="account-c", uic=4912,
        asset_type="CfdOnIndex", now=START+timedelta(hours=1),
        broker=Broker({"Data":[_activity()]}),
    )
    assert matched["order-1"]["execution_price"]==27031.35
    assert len(calls)==1
    assert calls[0][0]=="cs/v1/audit/orderactivities"
    assert calls[0][1]["AccountKey"]=="account-key-c"
    assert calls[0][1]["ClientKey"]=="client-key-c"
    assert calls[0][1]["$top"]==500
    with pytest.raises(ValueError,match="incomplete or paginated"):
        fetch_exact_final_fills_v1(
            [_event()], account_id="account-c", uic=4912,
            asset_type="CfdOnIndex", broker=Broker({
                "Data":[_activity()], "__next":"next-page",
            }),
        )
    assert len(calls)==2
