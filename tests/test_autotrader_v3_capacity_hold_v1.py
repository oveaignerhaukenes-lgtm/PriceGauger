from pathlib import Path

import pytest

from autotrader_v3_capacity_hold_v1 import (
    V3CapacityHold,
    capacity_hold_blocks_v3,
    clear_capacity_hold_v3,
    load_capacity_hold_v3,
    save_capacity_hold_v3,
)
from autotrader_v3_live_sizing_v1 import V3CapitalCapReached


def test_capacity_hold_persists_and_blocks_same_saturated_context(tmp_path):
    db=str(tmp_path/"capacity.db")
    save_capacity_hold_v3(
        trader_id="pilot",
        direction="LONG",
        cap_nok=300.0,
        inventory_amount=0.02,
        context_key="strategy|T2m",
        db_path=db,
    )
    hold=load_capacity_hold_v3(trader_id="pilot",db_path=db)
    assert hold is not None
    assert capacity_hold_blocks_v3(
        hold=hold,
        desired_direction="LONG",
        actual_amount=0.02,
        cap_nok=300.0,
        context_key="strategy|T2m",
    )


@pytest.mark.parametrize(
    ("direction","actual","cap","context"),
    [
        ("SHORT",0.02,300.0,"strategy|T2m"),   # opposite desired direction
        ("LONG",0.01,300.0,"strategy|T2m"),    # capacity freed by reduction
        ("LONG",0.02,350.0,"strategy|T2m"),    # budget/cap changed
        ("LONG",0.02,300.0,"strategy|T5m"),    # strategy/timeframe context changed
    ],
)
def test_capacity_hold_releases_when_context_or_capacity_changes(direction,actual,cap,context):
    hold=V3CapacityHold("pilot","LONG",300.0,0.02,"strategy|T2m")
    assert not capacity_hold_blocks_v3(
        hold=hold,
        desired_direction=direction,
        actual_amount=actual,
        cap_nok=cap,
        context_key=context,
    )


def test_flat_open_hold_stays_sticky_until_direction_or_settings_change():
    hold=V3CapacityHold("pilot","LONG",300.0,0.0,"strategy|T2m")
    assert capacity_hold_blocks_v3(
        hold=hold,desired_direction="LONG",actual_amount=0.0,
        cap_nok=300.0,context_key="strategy|T2m",
    )
    assert not capacity_hold_blocks_v3(
        hold=hold,desired_direction="SHORT",actual_amount=0.0,
        cap_nok=300.0,context_key="strategy|T2m",
    )


def test_clear_capacity_hold_is_scoped_to_trader(tmp_path):
    db=str(tmp_path/"capacity.db")
    for trader in ("a","b"):
        save_capacity_hold_v3(
            trader_id=trader,direction="LONG",cap_nok=300,
            inventory_amount=.02,context_key="x",db_path=db,
        )
    assert clear_capacity_hold_v3(trader_id="a",db_path=db)
    assert load_capacity_hold_v3(trader_id="a",db_path=db) is None
    assert load_capacity_hold_v3(trader_id="b",db_path=db) is not None


def test_runtime_treats_cap_as_managing_and_checks_hold_before_broker_precheck():
    source=Path("autotrader_v3_live_runtime_v1.py").read_text(encoding="utf-8")
    hold_check=source.index("capacity_hold_blocks_v3(")
    precheck=source.index("pre=broker.precheck(order)")
    cap_catch=source.index("except V3CapitalCapReached as exc:")
    assert hold_check < precheck < cap_catch
    window=source[cap_catch:cap_catch+1800]
    assert "'MANAGING'" in window
    assert "save_capacity_hold_v3(" in window
    assert "align_closed_bar_target_v3(" in window
    assert "broker.place_order" not in window


def test_expected_capacity_exception_remains_a_value_error():
    assert issubclass(V3CapitalCapReached, ValueError)
