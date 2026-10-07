from decimal import Decimal, ROUND_DOWN

import pytest

from autotrader_v3_execution_plan_v1 import ExecutionStepV3


def test_broker_amount_step_rounds_down_without_assuming_centilot_step():
    step = Decimal("1")
    requested = Decimal("5.9")
    assert (requested / step).to_integral_value(rounding=ROUND_DOWN) * step == Decimal("5")


def test_execution_step_from_amount_preserves_broker_quantity():
    assert ExecutionStepV3.from_amount("REDUCE", 1.0, "LONG", False, "test").amount == pytest.approx(1.0)
    assert ExecutionStepV3.from_amount("REDUCE", 0.03, "LONG", False, "test").amount == pytest.approx(0.03)


def test_runtime_normalizes_to_saxo_step_before_precheck():
    from pathlib import Path

    source = Path("autotrader_v3_live_runtime_v1.py").read_text()
    assert "step=Decimal(str(instrument_rules.increment_size))" in source
    assert source.index("permitted=(requested / step).to_integral_value(") < source.index("pre=broker.precheck(order)")
    assert "ExecutionStepV3.from_amount(" in source
    assert "ExecutionStepV3(mutation.action,float(permitted)" not in source
