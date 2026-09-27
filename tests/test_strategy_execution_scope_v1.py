from strategy_execution_scope_v1 import ExecutionAdapterScopeV1,assert_adapter_scope_match_v1
import pytest

def _scope(i:int)->ExecutionAdapterScopeV1:
    strategy=f"strategy-{i}"
    plan=f"plan-{i}"
    return ExecutionAdapterScopeV1(
        scope_id=f"{strategy}:{plan}",strategy_key=strategy,plan_id=plan,handoff_id=f"handoff-{i}",
        pilot_key=f"pilot-{i}",account_id=f"account-{i}",uic=10000+i,asset_type="CfdOnFutures",
        budget_nok=2000+i*100,exposure_pct=50,
    )

def test_fifteen_parallel_threads_never_cross_accept()->None:
    scopes=[_scope(i) for i in range(15)]
    for i,expected in enumerate(scopes):
        assert_adapter_scope_match_v1(expected,expected)
        for j,actual in enumerate(scopes):
            if i==j: continue
            with pytest.raises(ValueError,match="EXECUTION_ADAPTER_SCOPE_MISMATCH"):
                assert_adapter_scope_match_v1(expected,actual)

@pytest.mark.parametrize("field",["strategy_key","plan_id","handoff_id","pilot_key","account_id","uic","asset_type"])
def test_single_identity_mismatch_fails_closed(field:str)->None:
    a=_scope(1); values=a.__dict__ if hasattr(a,"__dict__") else {name:getattr(a,name) for name in a.__dataclass_fields__}
    values=dict(values)
    values[field]=values[field]+1 if field=="uic" else str(values[field])+"-wrong"
    if field in {"strategy_key","plan_id"}:
        values["scope_id"]=f"{values['strategy_key']}:{values['plan_id']}"
    b=ExecutionAdapterScopeV1(**values)
    with pytest.raises(ValueError,match="EXECUTION_ADAPTER_SCOPE_MISMATCH"):
        assert_adapter_scope_match_v1(a,b)

def test_budget_slider_is_scope_local()->None:
    a=_scope(1); b=_scope(2)
    assert a.max_exposure_nok != b.max_exposure_nok
