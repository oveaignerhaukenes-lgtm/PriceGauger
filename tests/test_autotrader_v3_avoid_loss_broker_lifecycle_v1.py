"""Pure OPEN/FLAT broker evidence gates; no Saxo calls or position mutation."""
from copy import deepcopy
import pytest

from autotrader_v3_avoid_loss_broker_lifecycle_v1 import (
    require_confirmed_final_fill_v1,
    validated_confirmed_open_anchor_v1,
    require_broker_confirmed_flat_v1,
)


def _valid(direction="Buy"):
    signed=0.01 if direction=="Buy" else -0.01
    stage={
        "guard_state":"RECONCILED","request_key":"durable-open",
        "broker_order_id":"order-1",
        "account_id":"acct","uic":4912,"asset_type":"CfdOnIndex",
        "signed_amount":signed,"submitted_amount":0.01,
        "submitted_side":direction,"expected_inventory":signed,
        "initial_margin_nok":1000.0,
    }
    audit={"available":True,"status":"FinalFill","sub_status":"Confirmed",
           "side":direction,"filled_amount":0.01,"position_id":"P123"}
    pos={"PositionId":"P123","PositionBase":{
        "AccountId":"acct","Uic":4912,"AssetType":"CfdOnIndex",
        "Amount":0.01,"Status":"Open"}}
    return stage,audit,pos,signed


def check(data):
    stage,audit,pos,signed=data
    return validated_confirmed_open_anchor_v1(
        account_id="acct",uic=4912,asset_type="CfdOnIndex",
        durable_entry=stage,audit_activity=audit,
        individual_position=pos,signed_net_inventory=signed)


@pytest.mark.parametrize("side",["Buy","Sell"])
def test_only_exact_reconciled_full_fill_confirms_margin_anchor(side):
    result=check(_valid(side))
    assert result.position_token=="P123"
    assert result.signed_amount==(0.01 if side=="Buy" else -0.01)
    assert result.entry_margin_nok==1000


@pytest.mark.parametrize("change",[
    lambda s,a,p: s.update(guard_state="SUBMITTED"),
    lambda s,a,p: s.update(initial_margin_nok=0),
    lambda s,a,p: s.update(initial_margin_nok=float("nan")),
    lambda s,a,p: s.update(account_id="other"),
    lambda s,a,p: s.update(asset_type="Stock"),
    lambda s,a,p: s.update(submitted_amount=0.02),
    lambda s,a,p: s.update(expected_inventory=0.02),
    lambda s,a,p: s.update(signed_amount=0.02),
    lambda s,a,p: s.update(submitted_side="Sell"),
    lambda s,a,p: s.update(broker_order_id=""),
    lambda s,a,p: a.update(status="Fill"),
    lambda s,a,p: a.update(status="FinalFill",sub_status="Pending"),
    lambda s,a,p: a.update(available=False),
    lambda s,a,p: a.update(filled_amount=0.005),
    lambda s,a,p: a.update(filled_amount=float("inf")),
    lambda s,a,p: a.update(position_id="P-else"),
    lambda s,a,p: a.update(side="Sell"),
    lambda s,a,p: p.update(PositionId="P-else"),
    lambda s,a,p: p["PositionBase"].update(AccountId="other"),
    lambda s,a,p: p["PositionBase"].update(Amount=0.02),
    lambda s,a,p: p["PositionBase"].update(Status="Closed"),
])
def test_wrong_durable_broker_audit_or_position_blocks_anchor(change):
    stage,audit,pos,signed=_valid()
    change(stage,audit,pos)
    with pytest.raises(ValueError):
        check((stage,audit,pos,signed))


def test_ambiguous_partial_or_missing_order_confirmation_is_not_success():
    activity=_valid()[1]
    for fields in (
        {"status":"Fill","sub_status":"Confirmed"},
        {"status":"FinalFill","sub_status":"Pending"},
        {"filled_amount":None},
        {"position_id":None},
    ):
        changed=dict(activity,**fields)
        with pytest.raises(ValueError):
            require_confirmed_final_fill_v1(
                activity=changed,expected_side="Buy",
                expected_amount=0.01,expected_position_id="P123")


def test_confirmed_broker_flat_requires_both_empty_sources_and_no_pending():
    require_broker_confirmed_flat_v1(
        account_scoped_net_rows=(),account_scoped_individual_rows=(),
        unresolved_order=False)
    for nets,individual,pending in [
        (({"NetPositionBase":{"AmountLong":0.01}},),(),False),
        ((),({"PositionId":"P123"},),False),
        ((),(),True),
        ((),(),None),
        (None,(),False),
        ((),None,False),
        (({"NetPositionBase":{"AmountLong":0.0}},),(),False),
    ]:
        with pytest.raises(ValueError):
            require_broker_confirmed_flat_v1(
                account_scoped_net_rows=nets,account_scoped_individual_rows=individual,
                unresolved_order=pending)


def test_exact_order_reconciled_stage_query_returns_boundary_and_state(tmp_path):
    """Real DB ledger stage is queryable with full context, never guessed."""
    from database import connect
    from autotrader_v3_avoid_loss_state_v1 import (
        stage_entry_preflight_v1,staged_entry_for_reconciled_order_v1,
    )
    db=str(tmp_path/"v3.db")
    with connect(db) as conn:
        conn.execute("""CREATE TABLE autotrader_v3_order_guard(
            request_key TEXT PRIMARY KEY,
            trader_id TEXT, account_id TEXT,uic INTEGER,asset_type TEXT,
            state TEXT, broker_order_id TEXT,submitted_side TEXT,
            submitted_amount REAL,expected_inventory REAL)""")
        conn.execute("""INSERT INTO autotrader_v3_order_guard(
            request_key,trader_id,account_id,uic,asset_type,state,broker_order_id,
            submitted_side,submitted_amount,expected_inventory)
            VALUES(?,?,?,?,?,?,?,?,?,?)""",
            ("req","inst","acct",4912,"CfdOnIndex","SUBMITTED","order-1",
             "Buy",.01,.01))
    stage_entry_preflight_v1(trader_id="inst",request_key="req",margin_nok=1000,
        account_id="acct",uic=4912,asset_type="CfdOnIndex",
        signed_amount=.01,db_path=db)
    kw={"trader_id":"inst","account_id":"acct","uic":4912,
        "asset_type":"CfdOnIndex","db_path":db}
    assert staged_entry_for_reconciled_order_v1(**kw) is None
    with connect(db) as conn:
        conn.execute("UPDATE autotrader_v3_order_guard SET state='RECONCILED'")
    staged=staged_entry_for_reconciled_order_v1(**kw)
    assert staged["guard_state"]=="RECONCILED"
    assert staged["account_id"]=="acct"
    assert staged["uic"]==4912
    result=validated_confirmed_open_anchor_v1(
        account_id="acct",uic=4912,asset_type="CfdOnIndex",
        durable_entry=staged,audit_activity=_valid()[1],
        individual_position=_valid()[2],signed_net_inventory=.01)
    assert result.entry_margin_nok==1000
