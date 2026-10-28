"""Exact-unit V3 fleet P/L display and non-virtualized mobile chart tests."""
import pytest

from autotrader_v3_fleet_pnl_display_v1 import (
    account_currency_v1,broker_open_pnl_for_fleet_v1,
    render_stable_fleet_pnl_html_v1,
)


def test_only_authoritative_base_currency_pnl_claims_nok():
    accounts=[{"AccountId":"A","Currency":"NOK"},
              {"AccountId":"B","Currency":"USD"}]
    assert account_currency_v1(accounts,"A")=="NOK"
    assert account_currency_v1(accounts,"B")=="USD"
    assert account_currency_v1(accounts,"missing") is None
    row={"NetPositionView":{
        "CalculationReliability":"Ok",
        "CurrentPriceDelayMinutes":0,
        "ProfitLossOnTradeInBaseCurrency":-2.35,
    }}
    pnl=broker_open_pnl_for_fleet_v1(net_position_rows=(row,),
                                     account_currency="NOK")
    assert pnl.amount==pytest.approx(-2.35)
    assert pnl.unit_verified
    assert pnl.unit_label=="NOK"
    assert not broker_open_pnl_for_fleet_v1(
        net_position_rows=(row,),account_currency=None).unit_verified


def test_fallback_dynamic_or_inferred_pnl_never_labeled_money():
    row={"NetPositionView":{},
         "NetPositionDynamic":{"OpenProfitLoss":-1.3}}
    detail=broker_open_pnl_for_fleet_v1(net_position_rows=(row,),
                                         account_currency="NOK")
    assert detail.amount==pytest.approx(-1.3)
    assert not detail.unit_verified
    assert detail.unit_label=="enhet uavklart"
    with pytest.raises(ValueError):
        broker_open_pnl_for_fleet_v1(
            net_position_rows=(row,row),account_currency="NOK")
    assert broker_open_pnl_for_fleet_v1(
        net_position_rows=(),account_currency="NOK").unit_label=="NOK"


def test_static_mobile_bars_display_signs_units_and_escaped_labels():
    html=render_stable_fleet_pnl_html_v1([
        {"label":"Tech A <script>alert('bad')</script>","amount":-2.0,
         "currency":"NOK"},
        {"label":"Tech E & gold","amount":5.0,"currency":"NOK"},
        {"label":"Test USD","amount":1.0,"currency":"USD"},
    ])
    assert 'st.bar_chart' not in html
    assert '<canvas' not in html
    assert 'class="pbar"' in html
    assert 'class="pneg"' in html
    assert 'class="ppos"' in html
    assert '−2.00 NOK' in html
    assert '+5.00 NOK' in html
    assert 'Test USD' in html
    assert '&lt;script&gt;' in html
    assert "<script>" not in html
    assert 'Tech E &amp; gold' in html
    assert html.count('class="pgroup"')==2
    assert "Åpen P/L" in html


def test_fleet_ui_disables_canvas_and_indicates_real_pnl_unit():
    from pathlib import Path
    text=Path("autotrader_v3_fleet_ui_v1.py").read_text()
    assert "st.bar_chart(" not in text
    assert "render_stable_fleet_pnl_html_v1(" in text
    assert "broker_open_pnl_for_fleet_v1(" in text
    assert "account_currency_v1(" in text
    assert "beløp, ikke prosent" in text
    assert "urealisert" in text
    assert "uavklart enhet" in text
