from live_mirror_comparison_v1 import summarize_pairs


def test_unmatched_and_unknown_are_not_successful_agreement():
    fill=dict(raw=.01,inventory_after=.01,outcome="FILLED",verified=True,
              side="BUY",amount=.01,price=100.,latency_s=3.)
    live={"a":fill,"b":dict(raw=0.,inventory_after=None,outcome="UNOBSERVED"),
          "c":dict(raw=0.,inventory_after=0.,outcome="NO_CHANGE")}
    sim={"a":dict(fill,price=101.,latency_s=4.),"b":dict(raw=0.,inventory_after=0.,outcome="NO_CHANGE"),
         "d":dict(raw=0.,inventory_after=0.,outcome="NO_CHANGE")}
    r=summarize_pairs(live,sim)
    assert r["union"]==4 and r["paired"]==2 and r["only_live"]==r["only_sim"]==1
    assert r["target_agreement"]==.5 and r["inventory_agreement"]==.25
    assert r["verified_fill_pairs"]==1 and r["price_mae_points"]==1
    assert r["latency_mae_s"]==1 and not r["passed"] and not r["pnl_validated"]


def test_no_data_is_not_perfect_parity():
    r=summarize_pairs({}, {})
    assert r["coverage"] is None and r["inventory_agreement"] is None and not r["passed"]
