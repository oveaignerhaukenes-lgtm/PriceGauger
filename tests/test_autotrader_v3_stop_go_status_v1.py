"""Operator STOP must be durable, instance-scoped and non-bypassable."""
from pathlib import Path

import pytest

from autotrader_v3_stop_go_status_v1 import load_v3_stop_go_lights_v1
from autotrader_v3_trade_filter_v1 import (
    load_trade_filter_v1,set_trade_filter_v1,allow_new_exposure_v1,
)


def test_default_go_and_durable_instance_stop(tmp_path):
    path=str(tmp_path/'filter.db')
    assert allow_new_exposure_v1(instance_id='a',strategy_key='s',db_path=path)
    assert load_trade_filter_v1(instance_id='a',strategy_key='s',db_path=path).mode=='GO'
    set_trade_filter_v1(instance_id='a',strategy_key='s',mode='STOP',db_path=path)
    assert not allow_new_exposure_v1(instance_id='a',strategy_key='s',db_path=path)
    assert allow_new_exposure_v1(instance_id='b',strategy_key='s',db_path=path)
    assert not allow_new_exposure_v1(instance_id='a',strategy_key='changed',db_path=path)
    assert load_v3_stop_go_lights_v1((('a','s',True),('b','s',True),
        ('c','s',False),('a2','s',True)),db_path=path)['a'].label=='STOPP'
    set_trade_filter_v1(instance_id='a',strategy_key='s',mode='GO',db_path=path)
    assert allow_new_exposure_v1(instance_id='a',strategy_key='s',db_path=path)


def test_ui_lights_match_live_latch_and_arming(tmp_path):
    path=str(tmp_path/'filter.db')
    set_trade_filter_v1(instance_id='a',strategy_key='s',mode='STOP',db_path=path)
    states=load_v3_stop_go_lights_v1((('a','s',True),('a-other','s',True),
        ('b','s',False),('c','s',True)),db_path=path)
    assert {key:light.symbol for key,light in states.items()}=={
        'a':'🔴','a-other':'🟢','b':'⚪','c':'🟢'}
    switched=load_v3_stop_go_lights_v1((('a','new-strategy',True),),db_path=path)
    assert switched['a'].label=='STOPP'


def test_unreadable_database_never_clears_stop_for_new_exposure(monkeypatch):
    import autotrader_v3_trade_filter_v1 as gate
    import autotrader_v3_stop_go_status_v1 as lights
    def broken(**kwargs):
        raise OSError('postgres disconnected')
    monkeypatch.setattr(gate,'load_trade_filter_v1',broken)
    monkeypatch.setattr(lights,'load_trade_filter_v1',broken)
    assert not gate.allow_new_exposure_v1(instance_id='a',strategy_key='s')
    assert load_v3_stop_go_lights_v1((('a','s',True),))['a'].label=='UKJENT'


def test_only_explicit_operator_can_set_latch(tmp_path):
    path=str(tmp_path/'filter.db')
    with pytest.raises(ValueError):
        set_trade_filter_v1(instance_id='a',strategy_key='s',mode='STOP',
                            source='VALIDATED_MODEL',db_path=path)
    with pytest.raises(ValueError):
        set_trade_filter_v1(instance_id='a',strategy_key='s',mode='MAYBE',db_path=path)
    with pytest.raises(ValueError):
        set_trade_filter_v1(instance_id='',strategy_key='s',mode='STOP',db_path=path)


def test_live_order_path_checks_twice_and_never_blocks_reductions():
    runtime=Path('autotrader_v3_live_runtime_v1.py').read_text(encoding='utf8')
    stop=runtime.index('mutation=next((s for s in plan.steps')
    post=runtime.index('result=broker.place_order(order,confirm_live=True)')
    decisions=runtime[stop:post]
    assert decisions.count('not allow_new_exposure_v1(')==2
    assert decisions.count("mutation.action in {'OPEN','ADD'} and not allow_new_exposure_v1(")==2
    assert decisions.index('not allow_new_exposure_v1(')<decisions.index('reserve_order_v3(')
    assert decisions.rindex('not allow_new_exposure_v1(')>decisions.index('claim_reserved_for_submission_v3(')
    assert 'mark_order_v3(request_key=request_key,state=\'REJECTED\'' in decisions
    assert 'align_closed_bar_target_v3(' in decisions
    ui=Path('autotrader_v3_fleet_ui_v1.py').read_text(encoding='utf8')
    assert 'light.symbol' in ui and 'light.label' in ui
    assert '⚪ AV/UKJENT' in ui
