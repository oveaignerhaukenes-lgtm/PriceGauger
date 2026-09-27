from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True,slots=True)
class ExecutionAdapterScopeV1:
    scope_id:str
    strategy_key:str
    plan_id:str
    handoff_id:str
    pilot_key:str
    account_id:str
    uic:int
    asset_type:str
    budget_nok:float
    exposure_pct:float

    def __post_init__(self)->None:
        expected=f"{self.strategy_key}:{self.plan_id}"
        if self.scope_id!=expected: raise ValueError("EXECUTION_SCOPE_ID_MISMATCH")
        for name,value in (("strategy_key",self.strategy_key),("plan_id",self.plan_id),("handoff_id",self.handoff_id),
                           ("pilot_key",self.pilot_key),("account_id",self.account_id),("asset_type",self.asset_type)):
            if not str(value).strip(): raise ValueError(f"{name} is required")
        if int(self.uic)<=0: raise ValueError("uic must be positive")
        if float(self.budget_nok)<=0: raise ValueError("budget_nok must be positive")
        if not 0<=float(self.exposure_pct)<=100: raise ValueError("exposure_pct must be in [0,100]")

    @property
    def max_exposure_nok(self)->float:
        return float(self.budget_nok)*float(self.exposure_pct)/100.0

def assert_adapter_scope_match_v1(expected:ExecutionAdapterScopeV1,actual:ExecutionAdapterScopeV1)->None:
    """Every identity dimension must match; no fallback by market name or strategy family."""
    fields=("scope_id","strategy_key","plan_id","handoff_id","pilot_key","account_id","uic","asset_type")
    mismatched=[f for f in fields if getattr(expected,f)!=getattr(actual,f)]
    if mismatched: raise ValueError("EXECUTION_ADAPTER_SCOPE_MISMATCH:"+",".join(mismatched))
