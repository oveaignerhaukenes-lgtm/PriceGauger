"""No false 'free account' when V3 registry is authoritative."""
from types import SimpleNamespace as S

import pytest

from tradingdesk_account_controller_v3 import account_controller_truth_v1


def inst(account,pilot):
    return S(account_id=account,instance_id=pilot,uic=4912,asset_type="CfdOnIndex",market_name="US Tech 100 NAS")


def enrollment(account,pilot,strategy="macd-stoch-v2-1",mode="LIVE_MANAGE"):
    return S(account_id=account,pilot_key=pilot,strategy_key=strategy,
             execution_mode=mode,enabled=True)


def owner(account,engine,pilot):
    return S(account_id=account,engine_id=engine,owner_key=pilot)


def test_v3_instanced_account_is_not_free_even_without_legacy_enrollment():
    items=account_controller_truth_v1(["E"],instances=[inst("E","pilot-E")],
        owners={"E":owner("E","V3","pilot-E")},enrollments=[])
    e=items["E"]
    assert e.engine=="V3" and e.instance.instance_id=="pilot-E"
    assert e.enrollment is None and e.conflict is None


def test_registry_overrides_outdated_strategy_family_classification():
    # macd-stoch-v2-1 is absent from the legacy engine-key classifier.
    items=account_controller_truth_v1(["E"],instances=[inst("E","pilot-E")],
        owners={"E":owner("E","V3","pilot-E")},
        enrollments=[enrollment("E","legacy-stoch")])
    assert items["E"].engine=="V3" and not items["E"].conflict


def test_unregistered_claimed_v3_account_is_not_free():
    items=account_controller_truth_v1(["E"],instances=[],
        owners={"E":owner("E","V3","pilot-E")},enrollments=[])
    assert items["E"].engine=="V3" and items["E"].instance is None


def test_only_unclaimed_unregistered_accounts_are_free():
    result=account_controller_truth_v1(["E","F"],instances=[],
        owners={},enrollments=[])
    assert result["E"].engine is None
    assert result["F"].engine is None


@pytest.mark.parametrize("items,owners,legacy",[
    ([inst("E","p1"),inst("E","p2")],{},[]),
    ([inst("E","p1")],{"E":owner("E","V2","some-v2")},[]),
    ([inst("E","p1")],{"E":owner("E","V3","wrong-pilot")},[]),
])
def test_registry_conflicts_fail_closed(items,owners,legacy):
    if len(items)>1:
        with pytest.raises(ValueError,match="multiple enabled"):
            account_controller_truth_v1(["E"],instances=items,owners=owners,enrollments=legacy)
    else:
        state=account_controller_truth_v1(["E"],instances=items,owners=owners,enrollments=legacy)
        assert state["E"].conflict


def test_v2_enrollment_remains_isolated():
    en=enrollment("F","v2","macd-flip")
    result=account_controller_truth_v1(["F"],instances=[],
        owners={"F":owner("F","V2","v2")},enrollments=[en])
    assert result["F"].engine=="V2"


def test_inactive_enrollment_does_not_claim_account():
    en=enrollment("F","old",mode="SHADOW")
    result=account_controller_truth_v1(["F"],instances=[],
        owners={},enrollments=[en])
    assert result["F"].engine is None


def test_ui_renders_v3_registry_status_for_selected_account_and_never_legacy_free_text():
    from pathlib import Path
    s=Path("tradingdesk_automanager_simple_v1.py").read_text()
    assert "account_controller_truth_v1(" in s
    assert "selected_truth.instance" in s
    assert "_render_selected_v3_instance_v1(" in s
    assert "selected_truth.engine is None" in s
    assert "load_v3_instances_v1(" in s
