from decimal import Decimal, ROUND_DOWN


def normalize(amount):
    step=Decimal("0.01")
    requested=Decimal(str(amount))
    nearest_steps=(requested / step).quantize(Decimal("1"))
    nearest=nearest_steps * step
    if abs(requested-nearest) <= Decimal("0.000000001"):
        requested=nearest
    return (requested / step).to_integral_value(rounding=ROUND_DOWN) * step


def test_float_noise_at_one_step_snaps_to_exact_centilot():
    assert normalize(0.03-0.02) == Decimal("0.01")


def test_float_noise_at_multiple_steps_snaps_exactly():
    assert normalize(0.07-0.03) == Decimal("0.04")


def test_genuine_fractional_excess_still_floors_to_saxo_step():
    assert normalize(0.019) == Decimal("0.01")


def test_genuine_substep_amount_remains_below_minimum():
    assert normalize(0.009) == Decimal("0.00")
