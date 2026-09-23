import unittest

from glass_sim.shuttle_yield_demo import Event, build_demo, validate


class ShuttleYieldTests(unittest.TestCase):
    def test_passing_time_accounting(self):
        result = build_demo()
        a, b = result["summary"][2:]
        self.assertEqual((a["completion_s"], b["completion_s"]), (7, 10))
        self.assertEqual((a["waiting_s"], b["lane_change_s"]), (3, 6))
        self.assertEqual(result, build_demo())

    def test_head_on_without_yield_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            validate([Event("A", "horizontal", 0, 4, "L0", "R0"),
                      Event("B", "horizontal", 0, 4, "R0", "L0")],
                     {"A": "L0", "B": "R0"}, {"A": "R0", "B": "L0"})

    def test_waiting_robot_remains_an_obstacle(self):
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            validate([Event("A", "horizontal", 0, 4, "L0", "R0"),
                      Event("B", "waiting", 0, 4, "R0", "R0")],
                     {"A": "L0", "B": "R0"}, {"A": "R0", "B": "R0"})

    def test_completed_robot_stays_parked(self):
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            validate([Event("A", "horizontal", 0, 4, "L0", "R0"),
                      Event("B", "waiting", 0, 5, "R1", "R1"),
                      Event("B", "yield", 5, 8, "R1", "R0")],
                     {"A": "L0", "B": "R1"}, {"A": "R0", "B": "R0"})

    def test_lane_change_sensitivity(self):
        result = build_demo(crab_s=5)
        self.assertEqual([r["completion_s"] for r in result["summary"][2:]], [9, 14])
