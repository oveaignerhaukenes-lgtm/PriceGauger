"""Contract tests: no LIVE orders, no stale news, no blind macro offsets."""
from datetime import datetime, timedelta, timezone
from math import cos, sin
import unittest

from tech100_crossmarket_forecast_v1 import (
    FACTORS, FactorReading, LabeledMarketMove, fit_crossmarket_model,
    forecast_crossmarket,
)
from tech100_four_channel_synthesis_v1 import (
    REGIME, IMPULSE, TECH_NEWS, MACRO_NEWS,
    ChannelSignal, synthesize,
)
from tech100_news_channels_v1 import (
    AssessedNewsItem, classify_news_topic, news_channel_signal,
)
from tech100_synthesis_routing_v1 import apply_entry_context, impulse_paper_intent


NOW = datetime(2026, 11, 20, 14, 0, tzinfo=timezone.utc)


def signal(channel, expected, *, at=NOW, horizon=5, validated=True, confidence=1.0):
    return ChannelSignal(channel, at, horizon, expected, confidence,
                         ("verified mock source",), validated)


class FourChannelContracts(unittest.TestCase):
    def test_one_of_four_is_selectable(self):
        result = synthesize(at=NOW, selected=[REGIME], signals=[signal(REGIME, 0.5)], horizon_minutes=5)
        self.assertEqual(result.status, "PAPER_ONLY")
        self.assertEqual(result.direction, "LONG")
        self.assertEqual([item.channel for item in result.contributions], [REGIME])

    def test_factors_can_cancel_and_neutral_means_flat(self):
        result = synthesize(at=NOW, selected=[REGIME, IMPULSE],
                            signals=[signal(REGIME, 0.6), signal(IMPULSE, -0.5)],
                            horizon_minutes=5)
        self.assertEqual(result.direction, "FLAT")
        self.assertAlmostEqual(result.expected_pct, 0.05)
        self.assertAlmostEqual(sum(x.weighted_pct for x in result.contributions), result.expected_pct)

    def test_all_modules_required_fail_closed(self):
        result = synthesize(at=NOW, selected=[REGIME, IMPULSE, TECH_NEWS, MACRO_NEWS],
                            signals=[signal(REGIME, 0.8), signal(IMPULSE, 0.5)], horizon_minutes=5)
        self.assertEqual(result.status, "INSUFFICIENT_EVIDENCE")
        self.assertEqual(result.direction, "FLAT")
        self.assertEqual(result.unavailable, (TECH_NEWS, MACRO_NEWS))

    def test_stale_future_unvalidated_and_wrong_horizon_abstain(self):
        for instance in (
            signal(IMPULSE, 1, at=NOW - timedelta(minutes=3)),
            signal(IMPULSE, 1, at=NOW + timedelta(seconds=1)),
            signal(IMPULSE, 1, validated=False),
            signal(IMPULSE, 1, horizon=60),
        ):
            with self.subTest(instance=instance):
                result = synthesize(at=NOW, selected=[IMPULSE], signals=[instance], horizon_minutes=5)
                self.assertEqual(result.direction, "FLAT")

    def test_context_support_never_blocks_exit(self):
        wrong = synthesize(at=NOW, selected=[REGIME],
                           signals=[signal(REGIME, -0.5)], horizon_minutes=5)
        self.assertEqual(apply_entry_context(result=wrong, held_side=1, proposed_side=0).allowed_target_side, 0)
        self.assertEqual(apply_entry_context(result=wrong, held_side=1, proposed_side=1).allowed_target_side, 1)
        self.assertEqual(apply_entry_context(result=wrong, held_side=0, proposed_side=1).allowed_target_side, 0)
        self.assertEqual(apply_entry_context(result=wrong, held_side=1, proposed_side=-1).allowed_target_side, -1)

    def test_dedicated_impulse_is_paper_only_idempotent_and_expires(self):
        accepted = synthesize(at=NOW, selected=[IMPULSE],
                              signals=[signal(IMPULSE, 0.5)], horizon_minutes=5)
        one = impulse_paper_intent(result=accepted, instance_key="Tech100-Impulse-Research")
        two = impulse_paper_intent(result=accepted, instance_key="Tech100-Impulse-Research")
        self.assertIsNotNone(one)
        self.assertEqual(one.signal_id, two.signal_id)
        self.assertFalse(one.live_authorized)
        self.assertEqual(one.target_side, 1)
        self.assertEqual(one.expires_at - one.created_at, timedelta(seconds=30))

    def test_regime_alone_does_not_spawn_impulse_order(self):
        accepted = synthesize(at=NOW, selected=[REGIME],
                              signals=[signal(REGIME, 0.5)], horizon_minutes=5)
        self.assertIsNone(impulse_paper_intent(result=accepted, instance_key="test"))


class CrossMarketPredictorContracts(unittest.TestCase):
    @staticmethod
    def sample(i):
        values = {
            "Gold": sin(i / 5),
            "Brent": cos(i / 7),
            "US2Y": sin(i / 9) * 4,
            "US10Y": cos(i / 11) * 5,
            "US30Y": sin(i / 13) * 3,
        }
        result = (0.4 * values["Gold"] - 0.6 * values["Brent"]
                  - 0.05 * values["US2Y"] + 0.03 * values["US10Y"]
                  + 0.02 * values["US30Y"])
        stamp = NOW - timedelta(minutes=240 - i)
        return LabeledMarketMove(stamp, stamp + timedelta(minutes=5), values, result)

    def test_purged_historical_fit_is_multivariate_and_not_intrinsically_live(self):
        rows = [self.sample(i) for i in range(210)]
        model = fit_crossmarket_model(rows, channel=IMPULSE, horizon_minutes=5)
        self.assertTrue(model.train_count <= 210 * .7 - 4)
        self.assertTrue(model.holdout_better_than_zero)
        readings = [FactorReading(name, 10 if name == "Brent" else 0, NOW)
                    for name in FACTORS]
        withheld = forecast_crossmarket(model, at=NOW, readings=readings)
        self.assertIsNone(withheld.signal.expected_tech100_return_pct)
        permitted = forecast_crossmarket(model, at=NOW, readings=readings,
                                         historical_data_quality_verified=True)
        self.assertIn("Brent", permitted.shock_factors)
        self.assertTrue(permitted.signal.validated_out_of_sample)
        self.assertLess(permitted.contributions_pct["Brent"], 0)

    def test_bad_horizon_or_future_information_cannot_train(self):
        rows = [self.sample(i) for i in range(210)]
        first = rows[0]
        rows[0] = LabeledMarketMove(first.observed_at, first.future_at + timedelta(minutes=1),
                                    first.factors, first.future_tech100_pct)
        with self.assertRaisesRegex(ValueError, "horizon"):
            fit_crossmarket_model(rows, channel=IMPULSE, horizon_minutes=5)

    def test_missing_yield_and_stale_input_are_not_silently_filled(self):
        rows = [self.sample(i) for i in range(210)]
        model = fit_crossmarket_model(rows, channel=IMPULSE, horizon_minutes=5)
        readings = [FactorReading(name, 0, NOW) for name in FACTORS]
        with self.assertRaisesRegex(ValueError, "exact"):
            forecast_crossmarket(model, at=NOW, readings=readings[:-1])
        stale = [FactorReading(name, 0, NOW - timedelta(minutes=11)) for name in FACTORS]
        with self.assertRaisesRegex(ValueError, "stale"):
            forecast_crossmarket(model, at=NOW, readings=stale)


class NewsSeparationContracts(unittest.TestCase):
    def test_relevance_does_not_create_direction(self):
        self.assertEqual(classify_news_topic("Nvidia AI spending jumps"), (TECH_NEWS,))
        self.assertEqual(classify_news_topic("Fed rate decision and CPI inflation"), (MACRO_NEWS,))
        self.assertEqual(classify_news_topic("A local sports result"), ())
        self.assertIsNone(news_channel_signal(channel=TECH_NEWS, at=NOW,
                                               horizon_minutes=5, news=()).expected_tech100_return_pct)

    def test_news_requires_received_before_decision_and_validated_impact(self):
        base = AssessedNewsItem("story-1", TECH_NEWS, "primary", NOW - timedelta(minutes=2),
                                NOW - timedelta(minutes=1), 5, 0.6, .9, True)
        late = AssessedNewsItem("story-2", TECH_NEWS, "primary", NOW - timedelta(minutes=2),
                                NOW + timedelta(minutes=1), 5, -1.0, 1, True)
        unverified = AssessedNewsItem("story-3", TECH_NEWS, "primary", NOW - timedelta(minutes=2),
                                      NOW - timedelta(minutes=1), 5, -3.0, 1, False)
        result = news_channel_signal(channel=TECH_NEWS, at=NOW, horizon_minutes=5,
                                     news=[base, base, late, unverified])
        self.assertAlmostEqual(result.expected_tech100_return_pct, 0.6)
        self.assertEqual(result.evidence, ("primary:story-1",))


if __name__ == "__main__":
    unittest.main()
