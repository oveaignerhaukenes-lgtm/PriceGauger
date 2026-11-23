"""Source regression for the time-critical Saxo exit path."""
from pathlib import Path


def test_close_reduce_do_not_call_optional_precheck():
    src = Path("autotrader_v3_live_runtime_v1.py").read_text(encoding="utf-8")
    fast = src.index("if mutation.action in {'CLOSE','REDUCE'}:")
    open_branch = src.index("else:", fast)
    precheck = src.index("pre=broker.precheck(order)", open_branch)
    final_post = src.index("result=broker.place_order(order,confirm_live=True)", precheck)
    assert fast < open_branch < precheck < final_post
    assert "pre={'PreCheckResult':'Ok'}" in src[fast:open_branch]
    assert "if mutation.action in {'OPEN','ADD'}:" in src[precheck:final_post]
    assert "claim_reserved_for_submission_v3(" in src[precheck:final_post]
    assert "IDLE_SAXO_CACHE_V1.verified_pre_submit(" in src[precheck:final_post]
    assert "mark_order_v3(request_key=request_key,state='UNKNOWN'" in src[final_post:]
