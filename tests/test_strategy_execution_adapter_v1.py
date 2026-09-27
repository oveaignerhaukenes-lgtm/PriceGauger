from strategy_execution_adapter_v1 import live_open_budget_supported_v1,require_live_open_budget_support_v1
from strategy_execution_scope_v1 import ExecutionAdapterScopeV1
from types import SimpleNamespace
import pytest

def test_strategy_lab_open_is_blocked_until_budget_is_end_to_end()->None:
    binding=SimpleNamespace(scope=ExecutionAdapterScopeV1(
      scope_id="gold:p1",strategy_key="gold",plan_id="p1",handoff_id="h1",pilot_key="pilot",
      account_id="acct",uic=1,asset_type="ContractFutures",budget_nok=2000,exposure_pct=50),
      execution_strategy_key="macd")
    assert live_open_budget_supported_v1(binding) is False
    with pytest.raises(ValueError,match="BUDGET_NOT_END_TO_END"):
        require_live_open_budget_support_v1(binding)
