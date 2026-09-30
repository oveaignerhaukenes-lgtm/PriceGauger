from decimal import Decimal, ROUND_DOWN


def test_trailing_order_step_rounds_down():
    step = Decimal('0.01')
    assert Decimal('0.019999999').quantize(step, rounding=ROUND_DOWN) == Decimal('0.01')
    assert Decimal('0.009999999').quantize(step, rounding=ROUND_DOWN) < step


def test_trailing_runtime_normalizes_before_precheck():
    from pathlib import Path
    source = Path("autotrader_v3_live_runtime_v1.py").read_text()
    assert source.index("permitted=requested.quantize(") < source.index('pre=broker.precheck(order)')
    assert 'mutation = ExecutionStepV3(mutation.action, float(permitted)' in source
