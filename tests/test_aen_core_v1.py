"""AEn Core v1 broker-free invariants."""
import unittest

from aen_core_v1 import (
    AEnConfig, Bar, Inventory, StructureEvent,
    confirmed_structure_events, evaluate_structure, change_timeframe,
)


class AEnCoreTests(unittest.TestCase):
    def setUp(self):
        self.cfg = AEnConfig(max_units=3)

    def event(self, kind, at=5):
        return StructureEvent(kind, at - 2, at, 100.0)

    def test_hl_opens_one_and_scales_once(self):
        opening = evaluate_structure(Inventory(), event=self.event("HL"), cfg=self.cfg, regime="LONG")
        self.assertEqual((opening.action, opening.target.units), ("OPEN", 1))
        again = evaluate_structure(opening.target, event=self.event("HL"), cfg=self.cfg, regime="LONG")
        self.assertEqual(again.action, "HOLD")
        scaled = evaluate_structure(opening.target, event=self.event("HL", 8), cfg=self.cfg, regime="LONG")
        self.assertEqual((scaled.action, scaled.target.units), ("ADD", 2))

    def test_short_symmetric(self):
        opening = evaluate_structure(Inventory(), event=self.event("LH"), cfg=self.cfg, regime="SHORT")
        self.assertEqual((opening.action, opening.target.side), ("OPEN", "SHORT"))
        added = evaluate_structure(opening.target, event=self.event("LH", 9), cfg=self.cfg, regime="SHORT")
        self.assertEqual(added.target.units, 2)

    def test_flip_must_flat_first(self):
        decision = evaluate_structure(Inventory("LONG", 2), event=self.event("LH"),
                                      cfg=self.cfg, regime="SHORT")
        self.assertEqual((decision.action, decision.target.side, decision.target.units),
                         ("FLAT", "HOLD", 0))

    def test_cap_one_prevents_pyramiding(self):
        cfg = AEnConfig(max_units=1)
        decision = evaluate_structure(Inventory("LONG", 1), event=self.event("HL"),
                                      cfg=cfg, regime="LONG")
        self.assertEqual(decision.action, "HOLD")

    def test_reduce_after_break_and_new_higher_cap(self):
        decision = evaluate_structure(Inventory("LONG", 3), event=self.event("LL"),
                                      cfg=self.cfg, regime="LONG", protected_level_broken=True)
        self.assertEqual((decision.action, decision.target.units), ("REDUCE", 2))
        lower_cap = evaluate_structure(Inventory("LONG", 3), event=self.event("HL"),
                                      cfg=AEnConfig(max_units=1), regime="LONG")
        self.assertEqual(lower_cap.target.units, 1)

    def test_structure_event_only_after_future_bars_close(self):
        bars = [
            Bar("0", 10, 8, 9), Bar("1", 12, 9, 10),
            Bar("2", 11, 7, 9), Bar("3", 14, 10, 12),
            Bar("4", 12, 8, 10), Bar("5", 16, 11, 13),
            Bar("6", 13, 9, 11), Bar("7", 12, 8, 10),
        ]
        cfg = AEnConfig(pivot_left=1, pivot_right=1)
        events = confirmed_structure_events(bars, cfg)
        self.assertTrue(all(e.known_index == e.pivot_index + 1 for e in events))
        self.assertTrue(all(e.known_index < len(bars) for e in events))
        prefix = confirmed_structure_events(bars[:5], cfg)
        self.assertTrue(all(e.known_index <= 4 for e in prefix))
        self.assertEqual(tuple(e for e in events if e.known_index <= 4), prefix)

    def test_timeframe_does_not_change_positions(self):
        self.assertEqual(change_timeframe(10, 2, can_switch=True), 2)
        self.assertEqual(change_timeframe(10, 2, can_switch=False), 10)
        with self.assertRaises(ValueError):
            change_timeframe(10, 3, can_switch=True)

    def test_invalid_inventory(self):
        with self.assertRaises(ValueError):
            Inventory("HOLD", 1)


if __name__ == "__main__":
    unittest.main()
