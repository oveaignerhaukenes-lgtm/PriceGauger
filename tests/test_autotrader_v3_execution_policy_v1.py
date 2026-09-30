import pytest
from autotrader_v3_execution_policy_v1 import ExecutionPolicyV3,save_execution_policy_v3,load_execution_policy_v3

def test_policy_persists_submission_time_notional_cap(tmp_path):
    db=str(tmp_path/'pg.db'); p=ExecutionPolicyV3('t',2000,35)
    save_execution_policy_v3(p,db_path=db)
    loaded=load_execution_policy_v3('t',db_path=db)
    assert loaded==p
    assert loaded.max_notional_nok==pytest.approx(700)

def test_policy_is_explicit_and_has_no_implicit_default(tmp_path):
    assert load_execution_policy_v3('missing',db_path=str(tmp_path/'pg.db')) is None
