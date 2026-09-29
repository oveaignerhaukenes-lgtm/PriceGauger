from decimal import Decimal, ROUND_DOWN


def test_trailing_order_step_rounds_down():
    step = Decimal('0.01')
    assert Decimal('0.019999999').quantize(step, rounding=ROUND_DOWN) == Decimal('0.01')
    assert Decimal('0.009999999').quantize(step, rounding=ROUND_DOWN) < step
