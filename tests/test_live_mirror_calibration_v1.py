from datetime import datetime,timezone
from types import SimpleNamespace
import pytest
from live_mirror_calibration_v1 import derive_observed_terms

CAL=SimpleNamespace(latency_p50=4.,latency_p95=8.,slippage_p50=.2)
BASE=dict(uic=4912,asset_type="CfdOnIndex",account_currency="NOK",margin_currency="NOK",
    commission_currency="NOK",long_commission=0.,short_commission=0.,instrument_currency="USD",
    conversion_rate=10.,contract_size=1.,reference_price=26000.,order_amount=.01,
    initial_margin=130.,minimum_lots=.01,side="Buy")


def test_terms_need_explicit_fx_margin_and_both_sides():
    rows=[BASE,dict(BASE,side="Sell"),BASE]
    terms=derive_observed_terms(rows,CAL,uic=4912,asset_type="CfdOnIndex")
    assert terms["nok_per_point_per_lot"]==10
    assert terms["margin_fraction"]==pytest.approx(.05)
    assert terms["latency_seconds"]==4
    assert terms["adverse_slippage_points"]==.2
    assert derive_observed_terms([BASE]*3,CAL,uic=4912,asset_type="CfdOnIndex") is None
    assert derive_observed_terms([dict(r,conversion_rate=None) for r in rows],
                                CAL,uic=4912,asset_type="CfdOnIndex") is None
    assert derive_observed_terms([dict(r,long_commission=1.) for r in rows],
                                CAL,uic=4912,asset_type="CfdOnIndex") is None
    assert derive_observed_terms(rows,CAL,uic=42,asset_type="CfdOnIndex") is None


def test_one_sided_prechecks_do_not_require_impossible_opposite_open():
    assert derive_observed_terms([BASE]*3,CAL,uic=4912,asset_type="CfdOnIndex",required_sides=("BUY",)) is not None
    assert derive_observed_terms([BASE]*3,CAL,uic=4912,asset_type="CfdOnIndex",required_sides=("SELL",)) is None
