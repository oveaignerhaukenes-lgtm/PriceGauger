"""Regression of PAPER-only timing diagnostics; no DB, LIVE or broker access."""
import unittest
from datetime import datetime, timedelta, timezone

from market_rhythm_phase_paper_v1 import (
    PAPER_WINDOWS, ResearchBarV1, _state_before, phase_outcomes_v1,
    compare_long_regime_clocks_v1,
)
from strategy_lab_v2_replay import ReplayCostsV2, ReplayEventV2, ReplayResultV2


T0 = datetime(2026, 11, 17, 12, tzinfo=timezone.utc)


def bars(prices, *, remove=()):
    return tuple(ResearchBarV1(
        market_name="US Tech 100 NAS", bar_time=(T0+timedelta(minutes=i)).isoformat(),
        open=float(p), high=float(p)+1., low=float(p)-1., close=float(p),
    ) for i,p in enumerate(prices) if i not in remove)


def result(events):
    return ReplayResultV2("PAPER", (), tuple(events), 0., len(events), 0., 0., 0, "TEST")


def event(minute, *, kind, before, after, price=100.):
    return ReplayEventV2(T0+timedelta(minutes=minute), "PAPER", kind,
                         before, after, price, 0., "simulated")


class PhasePaperTests(unittest.TestCase):
    def test_buy_adverse_and_exit_rebound_have_different_semantics(self):
        prices = [100.] * 75
        prices[30:35] = [98., 97., 96., 95., 94.]
        prices[40:45] = [103., 104., 105., 106., 107.]
        orders = (event(30, kind="OPEN", before=0., after=.01),
                  event(40, kind="CLOSE", before=.01, after=0.))
        observations = phase_outcomes_v1(bars(prices), result(orders))
        entry = next(x for x in observations if x["Hendelse"] == "Inngang/økning" and x["Etter min"] == 3)
        exit_ = next(x for x in observations if x["Hendelse"] == "Flat-utgang" and x["Etter min"] == 3)
        self.assertEqual(entry["Feilfase %"], 100.)
        self.assertEqual(exit_["Feilfase %"], 100.)
        self.assertLess(entry["Snitt videre punkter (posisjonsretning)"], 0.)
        self.assertGreater(exit_["Snitt videre punkter (posisjonsretning)"], 0.)

    def test_missing_minute_censors_multi_minute_outcome(self):
        prices = [100.] * 75
        prices[30] = 99.
        prices[32] = 95.
        observed = phase_outcomes_v1(
            bars(prices, remove=(31,)),
            result((event(30, kind="OPEN", before=0., after=.01),)),
        )
        self.assertEqual([x["Etter min"] for x in observed], [1])

    def test_state_uses_only_pre_fill_bars(self):
        before = [100. + i*.1 for i in range(35)]
        x = bars(before + [200.] * 20)
        y = bars(before + [1.] * 20)
        self.assertEqual(_state_before(x, 35), _state_before(y, 35))
        self.assertEqual(_state_before(x, 35), "Trend")

    def test_censored_last_bar_and_gap_never_imply_gain(self):
        x = bars([100.] * 30)
        self.assertEqual(phase_outcomes_v1(x, result((event(30,kind="OPEN",before=0.,after=.01),))), [])

    def test_paper_three_minute_does_not_change_live_timeframes(self):
        from autotrader_v3_registry_v1 import TIMEFRAMES_V3
        self.assertIn("3m", PAPER_WINDOWS)
        self.assertNotIn("3m", TIMEFRAMES_V3)

    def test_insufficient_market_history_is_not_ranked(self):
        costs=ReplayCostsV2(point_value_nok=10., spread_bps=3., variable_fee_bps=2.,fixed_fee_nok=1.)
        with self.assertRaises(ValueError):
            compare_long_regime_clocks_v1(bars([100.] * 150), costs)


if __name__ == "__main__":
    unittest.main()
