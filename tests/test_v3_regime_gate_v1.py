"""Safety contract for optional BULL/BEAR/SIDEWAYS V3 entry gating."""
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import autotrader_v3_regime_gate_v1 as gate


CLOCK = datetime(2026, 11, 23, 10, 16, tzinfo=timezone.utc)


def bars(changes, *, end=None, instrument_id=4912):
    end = end or CLOCK.replace(second=0, microsecond=0) - timedelta(minutes=1)
    values = [26000.0]
    for movement in changes:
        values.append(values[-1] + movement)
    first = end - timedelta(minutes=len(values) - 1)
    return tuple(SimpleNamespace(
        bar_time=(first + timedelta(minutes=i)).isoformat(),
        close=value, instrument_id=instrument_id,
    ) for i, value in enumerate(values))


class TestRegimeGateV1(unittest.TestCase):
    def test_default_is_off_and_durable_settings_are_instance_scoped(self):
        with tempfile.TemporaryDirectory() as temp:
            db = str(Path(temp) / "gate.sqlite")
            default = gate.load_regime_policy_v1(instance_id="A", strategy_key="long-v3", db_path=db)
            self.assertEqual(default.mode, "OFF")
            self.assertEqual(default.allowed_states, gate.STATES_V1)
            saved = gate.save_regime_policy_v1(
                instance_id="A", strategy_key="long-v3", mode="LIVE",
                allowed_states=("BULL", "BEAR"), trend_only=True,
                block_unknown=True, db_path=db,
            )
            self.assertEqual(saved.mode, "LIVE")
            self.assertEqual(gate.load_regime_policy_v1(
                instance_id="A", strategy_key="long-v3", db_path=db), saved)
            self.assertEqual(gate.load_regime_policy_v1(
                instance_id="B", strategy_key="long-v3", db_path=db).mode, "OFF")
            self.assertEqual(gate.load_regime_policy_v1(
                instance_id="A", strategy_key="short-v3", db_path=db).mode, "LIVE")

    def test_invalid_policy_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            db = str(Path(temp) / "gate.sqlite")
            common = dict(instance_id="A", strategy_key="s", db_path=db,
                          trend_only=True, block_unknown=False)
            for mode, states in (("AUTO", ("BULL",)), ("LIVE", ("UNKNOWN",)),
                                 ("LIVE", ("BULL", "BULL"))):
                with self.assertRaises(ValueError):
                    gate.save_regime_policy_v1(mode=mode, allowed_states=states, **common)

    def test_30m_uptrend_and_60m_downtrend(self):
        self.assertEqual(gate.classify_regime_v1(bars([3] * 30), now=CLOCK)[0], "BULL")
        self.assertEqual(gate.classify_regime_v1(bars([-3] * 30), now=CLOCK)[0], "BEAR")
        self.assertEqual(gate.classify_regime_v1(bars([-4] * 60), now=CLOCK)[0], "BEAR")
        state, evidence = gate.classify_regime_v1(
            bars([-4] * 30 + [1] * 30), now=CLOCK)
        self.assertEqual((state, evidence), ("SIDEWAYS", "30m og 60m er i konflikt"))

    def test_sideways_is_not_unknown(self):
        state, _ = gate.classify_regime_v1(bars([2, -2] * 30), now=CLOCK)
        self.assertEqual(state, "SIDEWAYS")
        self.assertEqual(gate.classify_regime_v1(bars([2] * 29), now=CLOCK)[0], "UNKNOWN")

    def test_missing_stale_and_future_bars_are_unknown(self):
        clean = bars([2] * 30)
        self.assertEqual(gate.classify_regime_v1(clean[:-1], now=CLOCK)[0], "UNKNOWN")
        self.assertEqual(gate.classify_regime_v1(clean[:5] + clean[6:], now=CLOCK)[0], "UNKNOWN")
        self.assertEqual(gate.classify_regime_v1(bars([2] * 30,
            end=CLOCK.replace(second=0, microsecond=0)), now=CLOCK)[0], "UNKNOWN")
        self.assertEqual(gate.classify_regime_v1(bars([2] * 30,
            end=CLOCK.replace(second=0, microsecond=0)-timedelta(minutes=2)), now=CLOCK)[0], "UNKNOWN")

    def test_trend_only_blocks_countertrend_and_optional_sideways(self):
        policy = gate.RegimePolicyV1("A", "s", mode="LIVE",
                                     allowed_states=("BULL", "BEAR"),
                                     trend_only=True, block_unknown=True)
        cases = (("BULL", "LONG", True), ("BULL", "SHORT", False),
                 ("BEAR", "LONG", False), ("BEAR", "SHORT", True),
                 ("SIDEWAYS", "SHORT", False), ("UNKNOWN", "LONG", False))
        for state, direction, expected in cases:
            self.assertEqual(gate.decide_regime_entry_v1(
                policy, state=state, direction=direction).allow_new_exposure, expected)
        permissive = gate.RegimePolicyV1(
            "A", "s", mode="LIVE", allowed_states=("SIDEWAYS",), trend_only=True)
        for direction in ("LONG", "SHORT"):
            self.assertTrue(gate.decide_regime_entry_v1(
                permissive, state="SIDEWAYS", direction=direction).would_allow)
            self.assertTrue(gate.decide_regime_entry_v1(
                permissive, state="UNKNOWN", direction=direction).would_allow)

    def test_off_shadow_never_veto_even_if_would_block(self):
        for mode in ("OFF", "SHADOW"):
            policy = gate.RegimePolicyV1("A", "s", mode=mode,
                                         allowed_states=(), block_unknown=True)
            decision = gate.decide_regime_entry_v1(policy, state="BULL", direction="LONG")
            self.assertFalse(decision.would_allow)
            self.assertTrue(decision.allow_new_exposure)

    def test_live_read_only_exact_instrument_and_no_http(self):
        policy = gate.RegimePolicyV1("A", "s", mode="LIVE",
                                     allowed_states=("BEAR",), trend_only=True)
        with patch.object(gate, "load_regime_policy_v1", return_value=policy), \
             patch.object(gate, "CanonicalMarketBarStoreV2") as store:
            store.return_value.load_instrument_range.return_value = bars([3] * 60)
            result = gate.check_regime_entry_v1(
                instance_id="A", strategy_key="s", instrument_id=42,
                direction="LONG", now=CLOCK)
            self.assertEqual(result.state, "BULL")
            self.assertFalse(result.allow_new_exposure)
            self.assertEqual(store.return_value.load_instrument_range.call_args.kwargs["instrument_id"], 42)

    def test_off_skips_bars_and_broken_gate_fails_closed(self):
        with patch.object(gate, "load_regime_policy_v1", return_value=gate.RegimePolicyV1("A", "s")), \
             patch.object(gate, "CanonicalMarketBarStoreV2") as store:
            allowed = gate.check_regime_entry_v1(
                instance_id="A", strategy_key="s", instrument_id=42,
                direction="LONG", now=CLOCK)
            self.assertTrue(allowed.allow_new_exposure)
            store.assert_not_called()
        with patch.object(gate, "load_regime_policy_v1", side_effect=OSError("database")):
            denied = gate.check_regime_entry_v1(
                instance_id="A", strategy_key="s", instrument_id=42, direction="LONG")
            self.assertEqual((denied.mode, denied.allow_new_exposure), ("ERROR", False))

    def test_live_runtime_two_checks_pre_and_post_reservation_exits_exempt(self):
        runtime = Path("autotrader_v3_live_runtime_v1.py").read_text(encoding="utf-8")
        section = runtime[runtime.index("mutation=next((s for s in plan.steps"):
                          runtime.index("result=broker.place_order(order,confirm_live=True)")]
        self.assertEqual(section.count("check_regime_entry_v1("), 2)
        self.assertLess(section.index("check_regime_entry_v1("), section.index("reserve_order_v3("))
        self.assertGreater(section.rindex("check_regime_entry_v1("),
                           section.index("claim_reserved_for_submission_v3("))
        self.assertIn("mutation.action in {'OPEN','ADD'}", section)
        self.assertIn("mark_order_v3(request_key=request_key,state='REJECTED'", section)



    def test_counter_is_durable_scoped_and_deduplicated(self):
        with tempfile.TemporaryDirectory() as temp:
            db = str(Path(temp) / "gate.sqlite")
            common = dict(instance_id="A", strategy_key="s", decision_key="bar-1",
                          action="OPEN", direction="LONG", db_path=db)
            live = gate.RegimePolicyV1("A", "s", mode="LIVE", allowed_states=("BEAR",))
            denied = gate.decide_regime_entry_v1(live, state="BULL", direction="LONG")
            allowed = gate.decide_regime_entry_v1(live, state="BEAR", direction="LONG")
            shadow = gate.decide_regime_entry_v1(
                gate.RegimePolicyV1("A", "s", mode="SHADOW", allowed_states=()),
                state="BULL", direction="LONG")
            self.assertEqual(gate.load_regime_block_count_v1(instance_id="A", db_path=db), 0)
            for _ in range(3):
                gate.record_regime_block_v1(**common, decision=denied)
            gate.record_regime_block_v1(**{**common, "decision_key": "bar-2"}, decision=denied)
            gate.record_regime_block_v1(**{**common, "instance_id": "B"}, decision=denied)
            gate.record_regime_block_v1(**{**common, "decision_key": "bar-3"}, decision=allowed)
            gate.record_regime_block_v1(**{**common, "decision_key": "bar-4"}, decision=shadow)
            gate.record_regime_block_v1(**{**common, "action": "CLOSE"}, decision=denied)
            self.assertEqual(gate.load_regime_block_count_v1(instance_id="A", db_path=db), 2)
            self.assertEqual(gate.load_regime_block_count_v1(instance_id="B", db_path=db), 1)
            with patch.object(gate, "connect", side_effect=OSError("db offline")):
                gate.record_regime_block_v1(**common, decision=denied)
                self.assertIsNone(gate.load_regime_block_count_v1(instance_id="A", db_path=db))

    def test_entry_directions_and_effective_preview_contract(self):
        self.assertEqual(gate.strategy_entry_directions_v1("macd-stoch-v21-r-long-flat-v3"), ("LONG",))
        self.assertEqual(gate.strategy_entry_directions_v1("impulse-catcher-short-tick-v1-1"), ("SHORT",))
        self.assertEqual(gate.strategy_entry_directions_v1("macd-stoch-v2-1"), ("LONG", "SHORT"))
        ui = Path("pages/0_Markedsfilter.py").read_text(encoding="utf-8")
        self.assertIn("elif result.allow_new_exposure:", ui)
        self.assertIn("on_change=save_changed", ui)
        self.assertNotIn('form_submit_button("Lagre regimefilter")', ui)
        self.assertIn("load_regime_block_count_v1(instance_id=item.instance_id)", ui)
        runtime = Path("autotrader_v3_live_runtime_v1.py").read_text(encoding="utf-8")
        self.assertEqual(runtime.count("record_regime_block_v1("), 2)



    def test_unreadable_price_data_obeys_saved_unknown_policy(self):
        for mode, block_unknown, expected in (
            ("OFF", True, True), ("SHADOW", True, True),
            ("LIVE", False, True), ("LIVE", True, False),
        ):
            policy = gate.RegimePolicyV1("A", "s", mode=mode, block_unknown=block_unknown)
            with patch.object(gate, "load_regime_policy_v1", return_value=policy), \
                 patch.object(gate, "CanonicalMarketBarStoreV2", side_effect=OSError("price data")):
                result = gate.check_regime_entry_v1(
                    instance_id="A", strategy_key="s", instrument_id=42,
                    direction="LONG", now=CLOCK)
                self.assertEqual(result.allow_new_exposure, expected)
                self.assertEqual(result.mode, mode)
                self.assertEqual(result.state, "UNKNOWN")


    def test_simple_presets_are_exact_and_survive_strategy_switch(self):
        with tempfile.TemporaryDirectory() as temp:
            db = str(Path(temp) / "gate.sqlite")
            for preset, allowed in gate.REGIME_PRESETS_V1.items():
                saved = gate.save_regime_preset_v1(
                    instance_id="A", strategy_key="old", preset=preset, db_path=db)
                current = gate.load_regime_policy_v1(
                    instance_id="A", strategy_key="new", db_path=db)
                self.assertEqual(gate.regime_preset_key_v1(current), preset)
                self.assertEqual(current.allowed_states, allowed)
                for direction in ("LONG", "SHORT"):
                    for state in gate.STATES_V1 + ("UNKNOWN",):
                        result = gate.decide_regime_entry_v1(current, state=state, direction=direction)
                        self.assertEqual(result.allow_new_exposure, preset == "OFF" or state in allowed)
                self.assertEqual(gate.load_regime_policy_v1(
                    instance_id="B", strategy_key="new", db_path=db).mode, "OFF")
            legacy = gate.RegimePolicyV1("A", "s", mode="SHADOW", allowed_states=("BULL",))
            self.assertEqual(gate.regime_preset_key_v1(legacy), "LEGACY")


if __name__ == "__main__":
    unittest.main()
