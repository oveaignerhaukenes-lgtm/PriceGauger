"""No Saxo or database I/O: deterministic exit-policy counterfactual tests."""
import unittest
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace

from autotrader_v3_profit_protection_paper_v1 import compare_exit_protection_v1


START=datetime(2026,11,19,tzinfo=timezone.utc)


def market(closes,opens=None,*,warmup=15):
    marks=[100.]*warmup+list(closes)
    opens=opens or {}
    out=[]
    for i,c in enumerate(marks):
        o=float(opens.get(i,100. if i<warmup else c))
        out.append(SimpleNamespace(
            bar_time=START+timedelta(minutes=i),open=o,
            high=max(o,float(c))+1,low=min(o,float(c))-1,
            close=float(c)))
    return tuple(out)


def costs():
    return SimpleNamespace(point_value_nok=1.,spread_bps=0.,
                           variable_fee_bps=0.,fixed_fee_nok=1.)


def event(minute,kind,before,after,price,cost=1.):
    return SimpleNamespace(at=START+timedelta(minutes=minute),kind=kind,
                           prior_lots=before,after_lots=after,
                           price=float(price),cost_nok=float(cost))


def do_test(bars,events,givebacks=(.25,.5,.75),**params):
    return compare_exit_protection_v1(
        replay=SimpleNamespace(events=events),bars=bars,
        costs=costs(),givebacks=givebacks,**params)


class ProfitProtectionResearchTest(unittest.TestCase):
    def test_drawdown_25_and_50_trigger_but_75_does_not(self):
        bars=market([110,120,109,110,110,100],opens={18:105})
        events=(event(15,'OPEN',0,1,100),event(20,'CLOSE',1,0,100))
        baseline,atr,p25,p50,p75=do_test(bars,events)
        self.assertEqual(baseline.scenario_net_nok,-2)
        self.assertEqual(atr.profit_exits,0)
        self.assertEqual([p.profit_exits for p in (p25,p50,p75)],[1,1,0])
        # Closed bar at 00:17 signalled; fill uses 00:18 OPEN=105,
        # not 00:17 close 109 or its hypothetical intrabar low/high.
        self.assertEqual(p50.scenario_net_nok,3)
        self.assertEqual(p50.difference_nok,5)
        self.assertEqual(p75.scenario_net_nok,-2)

    def test_mild_initial_spread_loss_does_not_force_immediate_exit(self):
        bars=market([99,96,95,92,90,90],opens={17:95})
        events=(event(15,'OPEN',0,1,100),event(20,'CLOSE',1,0,90))
        baseline,atr,protected=do_test(bars,events,givebacks=(.5,))
        self.assertEqual(baseline.scenario_net_nok,-12)
        self.assertEqual(atr.adverse_exits,1)
        self.assertEqual(protected.adverse_exits,1)
        self.assertEqual(protected.profit_exits,0)
        self.assertEqual(protected.scenario_net_nok,-7)

    def test_short_direction_is_symmetrical_and_future_wicks_are_ignored(self):
        bars=market([90,80,91,95,100,100],opens={18:95})
        events=(event(15,'OPEN',0,-1,100),event(20,'CLOSE',-1,0,100))
        _,_,guard=do_test(bars,events,givebacks=(.5,))
        self.assertEqual(guard.profit_exits,1)
        self.assertEqual(guard.scenario_net_nok,3)
        altered=list(bars)
        bar=bars[15]
        altered[15]=SimpleNamespace(**{**vars(bar),'high':1000.,'low':1.})
        _,_,same=do_test(tuple(altered),events,givebacks=(.5,))
        self.assertEqual(same.scenario_net_nok,guard.scenario_net_nok)

    def test_data_gap_cannot_be_crossed_for_protective_exit(self):
        bars=tuple(b for b in market([110,120,90,90,90,100])
                   if b.bar_time!=START+timedelta(minutes=17))
        events=(event(15,'OPEN',0,1,100),event(20,'CLOSE',1,0,100))
        _,_,guard=do_test(bars,events,givebacks=(.5,))
        self.assertEqual(guard.protective_exits,0)

    def test_not_enough_past_bars_disables_atr_stop(self):
        bars=market([96,90,90],warmup=0)
        events=(event(0,'OPEN',0,1,100),event(2,'CLOSE',1,0,90))
        baseline,_,protected=do_test(bars,events,givebacks=(.5,))
        self.assertEqual(protected.adverse_exits,0)
        self.assertEqual(protected.scenario_net_nok,baseline.scenario_net_nok)

    def test_no_baseline_early_reentry_is_fabricated(self):
        bars=market([110,120,109,110,110,100,100,100,100],
                    opens={18:109})
        events=(event(15,'OPEN',0,1,100),event(20,'CLOSE',1,0,100),
                event(21,'OPEN',0,1,100),event(23,'CLOSE',1,0,100))
        baseline,_,guard=do_test(bars,events,givebacks=(.5,))
        self.assertEqual(guard.episodes,2)
        self.assertEqual(guard.protective_exits,1)
        self.assertEqual(guard.scenario_net_nok,5)
        self.assertEqual(baseline.scenario_net_nok,-4)

    def test_complex_and_incomplete_episodes_excluded_without_invented_fills(self):
        bars=market([110,120,109,105,100,100,100])
        events=(event(15,'OPEN',0,1,100),event(16,'ADD',1,2,110),
                event(19,'CLOSE',2,0,100),event(20,'OPEN',0,1,100))
        baseline,_,guard=do_test(bars,events,givebacks=(.5,))
        self.assertEqual(guard.episodes,0)
        self.assertEqual(guard.complex_episodes_excluded,1)
        self.assertEqual(guard.incomplete_episodes_excluded,1)
        self.assertEqual(baseline.scenario_net_nok,0)

    def test_invalid_fraction_and_duplicate_times_rejected(self):
        bars=market([110,120,109,100])
        events=(event(15,'OPEN',0,1,100),event(18,'CLOSE',1,0,100))
        with self.assertRaises(ValueError):
            do_test(bars,events,givebacks=(0,))
        with self.assertRaises(ValueError):
            do_test(bars+(bars[-1],),events)

    def test_warmup_only_trade_is_not_misreported_as_selected_day_result(self):
        bars=market([110,120,109,105,100,100])
        events=(event(15,'OPEN',0,1,100),event(20,'CLOSE',1,0,100))
        absent=do_test(bars,events,window_start=START+timedelta(minutes=16))
        self.assertEqual(absent[0].episodes,0)
        present=do_test(bars,events,window_start=START+timedelta(minutes=15),
                        window_end=START+timedelta(minutes=20))
        self.assertEqual(present[0].episodes,1)


if __name__=='__main__':unittest.main()
