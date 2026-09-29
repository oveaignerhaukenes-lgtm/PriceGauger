from pathlib import Path

RUNTIME=Path('autotrader_v3_live_runtime_v1.py').read_text(encoding='utf-8')

def test_pending_reconciliation_precedes_strategy_signal():
    assert RUNTIME.index('pending=pending_order_v3(')<RUNTIME.index('bars=CanonicalMarketBarStoreV2(')
    assert RUNTIME.index('reconcile_pending_v3(')<RUNTIME.index('decision=evaluate_strategy_bar_v3(')
    assert 'continue\n        actual=_actual(e,observations)' in RUNTIME

def test_order_intent_is_persisted_before_saxo_post():
    assert RUNTIME.index('reserve_order_v3(')<RUNTIME.index('broker.place_order(order,confirm_live=True)')
    assert "state='SUBMITTING'" in RUNTIME
    assert "state='UNKNOWN'" in RUNTIME
    assert 'if not broker_order_id:' in RUNTIME
    assert "expected_inventory=actual.amount+signed_delta" in RUNTIME
