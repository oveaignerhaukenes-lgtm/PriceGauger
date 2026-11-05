"""Tests for the isolated read-only macro release BBO observer."""
from datetime import timedelta
from types import SimpleNamespace

import pytest

from database import connect
from live_sim_hyper_quotes_v1 import HyperQuoteRecorder
from macro_release_lag_observer_v1 import (
    HORIZONS, market_group, paper_followthrough, release_in_capture_window,
    releases, study_release,
)

EVENT = releases()[0][1]


def row(market, uic, sec, mid, spread=0.1, receive_delay=0):
    moment = EVENT + timedelta(seconds=sec)
    received = moment + timedelta(seconds=receive_delay)
    return {
        "market_name": market, "provider_uic": uic,
        "quote_at": moment.isoformat(), "received_at": received.isoformat(),
        "bid": mid - spread / 2, "ask": mid + spread / 2,
    }


def synthetic():
    return [
        row("Gold", 11, -1, 1000),
        row("US Tech 100 NAS", 4912, -1, 10000),
        row("Silver", 12, -1, 100),
        row("Gold", 11, 1, 1002),  # 20bp
        row("US Tech 100 NAS", 4912, 1, 10000),
        row("Silver", 12, 1, 100.1),
        row("US Tech 100 NAS", 4912, 4, 10010),  # 10bp
        row("US Tech 100 NAS", 4912, 64, 10030),
    ]


def test_nfp_schedule_and_non_event_gating():
    assert releases()[0][0] == "NFP"
    assert EVENT.isoformat() == "2026-11-06T13:30:00+00:00"
    assert release_in_capture_window(EVENT - timedelta(seconds=180))
    assert release_in_capture_window(EVENT + timedelta(seconds=900))
    assert not release_in_capture_window(EVENT - timedelta(seconds=181))
    assert not release_in_capture_window(EVENT + timedelta(seconds=901))


def test_name_recognition_and_exact_uic():
    assert market_group("US Tech 100 NAS") == "Tech100"
    assert market_group("XAUUSD Gold") == "Gull"
    assert market_group("XAGUSD Silver") == "Sølv"
    assert market_group("US 500") == "US500"
    assert market_group("Crude Oil Brent") is None


def test_macro_capture_only_in_release_window_and_tradable(tmp_path):
    capture = HyperQuoteRecorder(str(tmp_path / "quotes.sqlite"))
    def q(market, uic, at):
        return SimpleNamespace(
            market=market, uic=uic, asset_type="CfdOnFutures",
            bid=100, ask=100.5, observed_at=at.isoformat(),
        )
    before = EVENT - timedelta(seconds=185)
    during = EVENT - timedelta(seconds=5)
    assert not capture.observe(q("Gold", 11, before), tradable=True, now=before)
    assert capture.observe(q("Gold", 11, during), tradable=True, now=during)
    assert not capture.observe(q("Gold", 11, during), tradable=True, now=during)
    assert capture.observe(q("Silver", 12, during), tradable=True, now=during)
    assert not capture.observe(q("Silver", 13, during), tradable=False, now=during)
    assert not capture.observe(q("Brent", 100, during), tradable=True, now=during)
    with connect(str(tmp_path / "quotes.sqlite")) as db:
        rows = db.execute("SELECT DISTINCT market_name FROM lsim_hyper_quotes_1s").fetchall()
    assert {x["market_name"] for x in rows} == {"Gold", "Silver"}


def test_gold_precedes_tech_and_no_cross_uic_mix():
    data = synthetic()
    data += [row("US Tech 100 NAS", 9999, -1, 9000),
             row("US Tech 100 NAS", 9999, 2, 9015)]
    report = study_release(data, event=EVENT, threshold_bps=5)
    assert report["tech_minus_gold_first_threshold_seconds"] == 3
    gold = next(x for x in report["markets"] if x["market"] == "Gull")
    tech = next(x for x in report["markets"] if x["market"] == "Tech100")
    assert gold["first_move"]["seconds"] == 1
    assert tech["first_move"]["seconds"] == 4
    assert tech["uic"] == 4912
    assert tech["quality"] == "OK"
    assert tech["returns_bps"][5] is None  # NO fabricated 5-second quote
    assert len(report["all_sources"]) == 4


def test_missing_pre_quote_or_gap_must_withhold_latency():
    late = [row("Gold", 11, -1, 1000), row("Gold", 11, 10, 1002),
            row("US Tech 100 NAS", 4912, -1, 10000),
            row("US Tech 100 NAS", 4912, 4, 10010)]
    report = study_release(late, event=EVENT)
    assert report["tech_minus_gold_first_threshold_seconds"] is None
    gold = next(x for x in report["markets"] if x["market"] == "Gull")
    assert gold["quality"] == "GAP_OR_MISSING_BASELINE"
    assert gold["first_move"] is None
    assert gold["indicative_move"] is not None


def test_paper_entry_after_received_gold_signal_plus_latency():
    paper = paper_followthrough(synthetic(), event=EVENT, latency_seconds=3, hold_seconds=60)
    assert paper["status"] == "PAPER_BBO_PROXY_ONLY"
    assert paper["signal_direction"] == "LONG"
    assert paper["entry_received_at"] == (EVENT + timedelta(seconds=4)).isoformat()
    assert paper["exit_received_at"] == (EVENT + timedelta(seconds=64)).isoformat()
    assert paper["net_after_spread_bps"] > 0


def test_late_received_quote_is_not_retroactive_signal():
    quotes = synthetic()
    gold = next(x for x in quotes if x["market_name"] == "Gold" and
                x["quote_at"] == (EVENT + timedelta(seconds=1)).isoformat())
    gold["received_at"] = (EVENT + timedelta(seconds=12)).isoformat()
    report = study_release(quotes, event=EVENT)
    gold_state = next(x for x in report["markets"] if x["market"] == "Gull")
    assert gold_state["first_move"] is None
    assert report["tech_minus_gold_first_threshold_seconds"] is None


def test_no_execution_imports_or_unsafe_authority():
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    nav = (root / "navigation_config.py").read_text()
    assert '"page": "pages/0_Macro_Release_Lag.py"' in nav
    for file in ("macro_release_lag_observer_v1.py", "pages/0_Macro_Release_Lag.py"):
        source = (root / file).read_text()
        for forbidden in ("place_order(", "run_v3_live_cycle_v1",
                          "import saxo_trading", "submit_order("):
            assert forbidden not in source
