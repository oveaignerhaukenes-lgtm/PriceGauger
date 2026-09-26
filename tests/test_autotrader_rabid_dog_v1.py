from datetime import datetime, timedelta, timezone

from autotrader_rabid_dog_v1 import RabidDog, RabidDogConfig


START = datetime(2026, 9, 25, 14, 0, tzinfo=timezone.utc)


def quote(model, seconds, mid, spread=1.0):
    return model.on_quote(START + timedelta(seconds=seconds), mid - spread / 2, mid + spread / 2)


def test_hysteresis_captures_long_run_and_direct_short_reversal():
    dog = RabidDog()
    assert quote(dog, 0, 100) is None
    long = quote(dog, 1, 104)
    assert long.target == "LONG" and long.order_amount == 0.01
    assert quote(dog, 2, 110) is None
    assert quote(dog, 3, 108) is None
    short = quote(dog, 4, 106)
    assert short.target == "SHORT" and short.order_amount == 0.02
    assert short.orders_last_hour == 2
    # Long bought at 104.5 and sold at 105.5: one point after spread.
    assert short.realized_points == 1.0


def test_hourly_budget_reserves_last_order_for_flat():
    dog = RabidDog(RabidDogConfig(orders_per_hour=3))
    quote(dog, 0, 100)
    assert quote(dog, 1, 104).target == "LONG"
    assert quote(dog, 2, 100).target == "SHORT"
    end = quote(dog, 3, 104)
    assert end.target == "FLAT" and end.reason == "ORDER_BUDGET_RESERVED"
    assert end.orders_last_hour == 3 and end.order_amount == 0.01
    assert quote(dog, 4, 110) is None
    assert dog.target == "FLAT"


def test_spread_and_one_second_limit_block_thrash():
    dog = RabidDog()
    quote(dog, 0, 100)
    assert quote(dog, 0.5, 105).target == "LONG"
    assert quote(dog, 0.8, 95) is None
    assert quote(dog, 1.0, 95, spread=6) is None
    assert dog.target == "LONG"


def test_stale_or_out_of_order_quotes_do_not_revise_state():
    dog = RabidDog()
    quote(dog, 0, 100)
    quote(dog, 1, 104)
    assert quote(dog, 1, 80) is None
    gap = quote(dog, 8, 106)
    assert gap.target == "FLAT" and gap.reason == "QUOTE_GAP"
    assert quote(dog, 9, 106) is None
